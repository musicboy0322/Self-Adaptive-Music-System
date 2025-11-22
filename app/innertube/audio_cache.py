import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Any
import time
import random

import yt_dlp

logger = logging.getLogger(__name__)

class AudioCacheManager:
    def __init__(self, max_cache_size_mb: int, cache_duration_hours: int, audio_quality_kbps: int, loudness_normalization: bool, song_quality_profiles: Dict[str, Dict[str, Any]], song_quality: str):
        self.cache_dir = tempfile.mkdtemp(prefix="cartunes_audio_")
        self.cached_files: Dict[
            str, dict] = {}  # video_id -> {path, downloaded_at, last_ordered_at, size}
        self.download_events: Dict[str, asyncio.Event] = {} # Track currently downloading videos by asyncio.Event
        self.max_cache_size_mb = max_cache_size_mb
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.audio_quality = str(audio_quality_kbps)
        self.loudness_normalization = loudness_normalization
        self.ffmpeg_path = shutil.which('ffmpeg')
        self.song_quality = song_quality
        self.song_quality_profiles = song_quality_profiles
        self.cache_hits = 0
        self.cache_misses = 0
        self.download_time = []
        if self.ffmpeg_path:
            logger.warning(f"Found ffmpeg at: {self.ffmpeg_path}")
        else:
            logger.warning(f"ffmpeg not found in PATH, using yt-dlp defaults.")
        logger.info(f"Audio cache initialized at: {self.cache_dir}")
        logger.info(
            f"Cache settings: {self.max_cache_size_mb}MB max, "
            f"{cache_duration_hours}h duration, {self.audio_quality}kbps quality, "
            f"Normalize Audio: {loudness_normalization}")

    def get_cache_path(self, video_id: str) -> Optional[str]:
        """Get cached file path if exists and valid"""
        if video_id in self.cached_files:
            file_info = self.cached_files[video_id]
            file_path = file_info['path']

            if (os.path.exists(file_path) and
                    datetime.now() - file_info['last_ordered_at'] < self.cache_duration):
                self.cache_hits += 1  
                return file_path
            else:
                self._remove_from_cache(video_id)

        self.cache_misses += 1       
        return None

    def is_downloading(self, video_id: str) -> bool:
        """Check if video is currently being downloaded"""
        return video_id in self.download_events

    def refresh_cache_timer(self, video_id: str):
        """Refresh the cache timer for a song when it's ordered again"""
        if video_id in self.cached_files:
            self.cached_files[video_id]['last_ordered_at'] = datetime.now()
            logger.debug(f"Refreshed cache timer for {video_id}")

    async def download_audio(self, video_id: str, priority: bool = False) -> Optional[str]:
        """Mock yt-dlp-like download but without real network."""
        start = time.time()

        # 1. 如果正在下載 → 等它下載完
        if video_id in self.download_events:
            await self.download_events[video_id].wait()
            self.refresh_cache_timer(video_id)
            return self.get_cache_path(video_id)

        # 2. 如果 cache 有 → 直接回傳
        cached = self.get_cache_path(video_id)
        if cached:
            self.refresh_cache_timer(video_id)
            return cached

        # 3. 標記 this video 正在下載
        self.download_events[video_id] = asyncio.Event()

        try:
            profile = self.song_quality_profiles[self.song_quality]

            # === 使用 chunk-based yt-dlp 模擬器 ===
            downloaded_file = await self._simulate_ytdlp_download(video_id, profile)

            # === 加入 cache 記錄 ===
            now = datetime.now()
            size_bytes = os.path.getsize(downloaded_file)

            self.cached_files[video_id] = {
                "path": downloaded_file,
                "downloaded_at": now,
                "last_ordered_at": now,
                "size": size_bytes
            }

            elapsed = time.time() - start
            self.download_time.append(elapsed)
            logger.info(f"[Mock yt-dlp] {video_id} finished in {elapsed:.2f}s ({self.song_quality})")

            return downloaded_file

        finally:
            # 解除鎖定
            self.download_events[video_id].set()
            del self.download_events[video_id]


    async def _download_file(self, video_id: str) -> Optional[str]:
        """Actually download the audio file"""
        try:
            # Clean cache if needed
            await self._cleanup_cache()

            url = f'https://www.youtube.com/watch?v={video_id}'

            # Configure yt-dlp to extract audio and convert to MP3 using ffmpeg
            ydl_opts = {
                'format': 'bestaudio/best',  # Select the best audio format
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',  # Convert to MP3
                    'preferredquality': self.audio_quality,  # Use configurable quality
                }],
                'outtmpl': os.path.join(self.cache_dir, f'{video_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ffmpeg_location': self.ffmpeg_path
            }

            def download_sync():
                # This function runs in a separate thread to avoid blocking
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)

            await asyncio.to_thread(download_sync)
            # The output file will now always be .mp3 due to postprocessor
            downloaded_file = os.path.join(self.cache_dir, f'{video_id}.mp3')

            if not os.path.exists(downloaded_file):
                logger.error(
                    f"Downloaded MP3 file not found for video {video_id} "
                    f"after yt_dlp.extract_info.")
                # Fallback: try to find any file that starts with the video ID
                cache_files = os.listdir(self.cache_dir)
                found_fallback = False
                for file in cache_files:
                    if file.startswith(video_id):
                        downloaded_file = os.path.join(self.cache_dir, file)
                        logger.info(
                            f"Found file by prefix match as fallback: {downloaded_file}")
                        found_fallback = True
                        break
                if not found_fallback:
                    return None

            async def _normalize_audio():
                # Start to normalize loudness
                normalized_file = os.path.join(self.cache_dir, f'{video_id}_normalized.mp3')
                normalization_cmd = [
                    self.ffmpeg_path, "-y", "-loglevel", "error", "-i",
                    downloaded_file, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    normalized_file
                ]

                logger.info(f"Normalizing loudness for {video_id}...")
                process = await asyncio.create_subprocess_exec(
                    *normalization_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await process.wait()
                if process.returncode != 0:
                    logger.error(f"Normalization failed for {video_id}")
                    return

                # Replace original with normalized version
                os.remove(downloaded_file)
                os.rename(normalized_file, downloaded_file)
                logger.info(f"Loudness normalized and saved: {downloaded_file}")
           
            if self.loudness_normalization:
                await _normalize_audio()

            # Add to cache with both timestamps
            current_time = datetime.now()
            file_size = os.path.getsize(downloaded_file)
            self.cached_files[video_id] = {
                'path': downloaded_file,
                'downloaded_at': current_time,
                'last_ordered_at': current_time,  # Same as download time initially
                'size': file_size
            }

            logger.info(
                f"Audio downloaded and converted to MP3 for {video_id}: "
                f"{downloaded_file} ({file_size} bytes) at {self.audio_quality}kbps")
            return downloaded_file

        except Exception as e:
            logger.error(f"Error downloading or converting audio for {video_id}: {e}")
            return None

    async def _cleanup_cache(self):
        """Remove old files and maintain cache size limit"""
        # Remove expired files (based on last_ordered_at)
        expired_videos = []
        for video_id, file_info in self.cached_files.items():
            if datetime.now() - file_info['last_ordered_at'] > self.cache_duration:
                expired_videos.append(video_id)

        for video_id in expired_videos:
            self._remove_from_cache(video_id)

        # If still oversize limit, remove the oldest files (by last_ordered_at)
        total_size_mb = self._get_total_cache_size_mb()
        if total_size_mb >= self.max_cache_size_mb:
            # Sort by last_ordered_at and remove oldest
            sorted_files = sorted(
                self.cached_files.items(),
                key=lambda x: x[1]['last_ordered_at']
            )

            # Remove files until under limit
            for video_id, file_info in sorted_files:
                if total_size_mb < self.max_cache_size_mb:
                    break
                self._remove_from_cache(video_id)
                total_size_mb = self._get_total_cache_size_mb()

    def _get_total_cache_size_mb(self) -> float:
        """Get total cache size in MB"""
        total_size_bytes = sum(file_info['size'] for file_info in self.cached_files.values())
        return total_size_bytes / (1024 * 1024)  # Convert to MB

    def _remove_from_cache(self, video_id: str):
        """Remove file from cache and filesystem"""
        if video_id in self.cached_files:
            file_path = self.cached_files[video_id]['path']
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Removed cached file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing cached file {file_path}: {e}")

            del self.cached_files[video_id]

    async def preload_queue_songs(self, video_ids: list, song_quality: str, preload_song: int):
        """Preload upcoming songs in background"""
        for video_id in video_ids[:preload_song]:  # Only preload next 5 songs
            if not self.get_cache_path(video_id) and not self.is_downloading(video_id):
                # Download in background without waiting
                asyncio.create_task(self.download_audio(video_id, song_quality))

    def cleanup_all(self):
        """Clean up all cached files and temp directory"""
        try:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
                logger.info(f"Cleaned up audio cache directory: {self.cache_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up cache directory: {e}")
        
    def set_max_cache_size(self, new_size_mb: int):
        """Dynamically adjust maximum cache size (in MB)."""
        old_size = self.max_cache_size_mb
        self.max_cache_size_mb = new_size_mb
        logger.info(f"[Adaptive] Cache size adjusted from {old_size}MB to {new_size_mb}MB")
    
    def get_download_time(self):
        result = self.download_time
        self.download_time.clear()
        return result

    def set_song_quailty(self, song_quality: str):
        self.song_quality = song_quality
    
    def get_song_quality(self):
        return self.song_quality

    def get_total_cache_usage(self) -> float:
        """Return current cache usage ratio (0.0 ~ 1.0)."""
        if self.max_cache_size_mb <= 0:
            return 0.0 
        current = self._get_total_cache_size_mb()
        return round(current / self.max_cache_size_mb, 4)
    
    def get_cache_hit_and_miss(self) -> [int, int]:
        return (self.cache_hits, self.cache_misses)
    
    def record_playback_latency(self, latency: float):
        if not hasattr(self, "playback_latencies"):
            self.playback_latencies = []
        self.playback_latencies.append(latency)

    def get_playback_latency(self):
        if not hasattr(self, "playback_latencies") or not self.playback_latencies:
            return 0.0
        result = self.playback_latencies
        self.playback_latencies.clear()
        return result

    def cpu_heavy(self, seconds: float):
        """CPU heavy loop (simulate ffmpeg encode)."""
        end = time.time() + seconds
        x = 0
        while time.time() < end:
            x += 1


    def io_write_chunk(self, path: str, bytes_n: int):
        """Simulate writing chunk to disk."""
        with open(path, "ab") as f:
            f.write(os.urandom(bytes_n))

    async def _simulate_ytdlp_download(self, video_id: str, profile: dict):
        """
        High-load yt-dlp + ffmpeg simulator:
        - heavy network chunk simulation
        - multi-core CPU encode/decode
        - heavy disk writes + fsync
        - threadpool saturation
        - jitter, tail latency, freezing stalls
        """

        loop = asyncio.get_running_loop()

        total_size_mb = profile.get("file_size_mb", 5)
        avg_download_time = random.uniform(*profile["avg_download_time_range"])
        chunks = 140 + random.randint(-20, 20)

        chunk_size = int((total_size_mb * 1024 * 1024) / chunks)

        net_total = avg_download_time * 0.65
        cpu_total = avg_download_time * 0.35

        net_per_chunk = net_total / chunks
        cpu_per_chunk = cpu_total / chunks

        cpu_parallelism = profile.get("cpu_threads", 4)

        temp_path = os.path.join(self.cache_dir, f"{video_id}.tmp")
        if os.path.exists(temp_path):
            os.remove(temp_path)

        if random.random() < 0.3:
            stall = random.uniform(0.4, 1.8)
            await asyncio.sleep(stall)

        for c in range(chunks):

            jitter = random.uniform(-0.2, 0.8)
            delay = max(0, net_per_chunk * (1 + jitter))

            if random.random() < 0.05:
                delay += random.uniform(0.5, 1.5)

            await asyncio.sleep(delay)

            cpu_tasks = [
                loop.run_in_executor(None, self.cpu_heavy, cpu_per_chunk / cpu_parallelism)
                for _ in range(cpu_parallelism)
            ]

            if random.random() < 0.3:
                cpu_tasks.append(
                    loop.run_in_executor(None, self.cpu_heavy, cpu_per_chunk * 0.2)
                )

            await asyncio.gather(*cpu_tasks)

            extra_cpu_tasks = [
                loop.run_in_executor(None, self.cpu_heavy, cpu_per_chunk * 0.08)
                for _ in range(8)
            ]

            async def _bg_cpu():
                await asyncio.gather(*extra_cpu_tasks)

            asyncio.create_task(_bg_cpu())
            await loop.run_in_executor(None, self.io_write_chunk, temp_path, chunk_size)

        ffmpeg_cpu_time = random.uniform(1.0, 2.5)
        await loop.run_in_executor(None, self.cpu_heavy, ffmpeg_cpu_time)

        final_path = os.path.join(self.cache_dir, f"{video_id}.mp3")
        if os.path.exists(final_path):
            os.remove(final_path)

        os.rename(temp_path, final_path)

        await loop.run_in_executor(None, self.io_write_chunk, final_path, 1024)

        return final_path
