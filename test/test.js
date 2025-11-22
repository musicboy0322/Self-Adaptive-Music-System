import http from "k6/http";
import { check, sleep } from "k6";

// const baseUrl = "http://cartunes-app-acmeair-group6.mycluster-ca-tor-1-835845-04e8c71ff333c8969bc4cbc5a77a70f6-0000.ca-tor.containers.appdomain.cloud"
const baseUrl = "http://127.0.0.1:8000";

const totalUser = 200;
const createRoomPercentage = 0.1;
const joinRoomPercentage = 0.3;
const addSongPercentage = 0.2;
const checkPlaybackPercentage = 0.4;

export const options = {
  scenarios: {
    creators: {
      executor: "constant-vus",
      vus: Math.round(totalUser * createRoomPercentage),
      duration: "20s",
      exec: "createRoom",
    },
    joiners: {
      executor: "constant-vus",
      vus: Math.round(totalUser * joinRoomPercentage),
      duration: "20s",
      exec: "joinRoom",
      startTime: "5s",
    },
    adders: {
      executor: "constant-vus",
      vus: Math.round(totalUser * addSongPercentage),
      duration: "25s",
      exec: "addSong",
      startTime: "10s",
    },
    playback_ready: {
      executor: "constant-vus",
      vus: Math.round(totalUser * checkPlaybackPercentage),
      duration: "20s",
      exec: "checkPlaybackReady",
      startTime: "15s",
    },
  },
};

export function setup() {
  const rooms = [];
  for (let i = 1; i <= 10; i++) {
    const res = http.post(
      `${baseUrl}/api/room/create?user_id=creator_${i}&user_name=Creator_${i}`
    );
    check(res, { "room created": (r) => r.status === 200 });
    rooms.push(res.json("room_id"));
  }

  const joiners = [];
  for (let i = 1; i <= 10; i++) {
    const room = rooms[Math.floor(Math.random() * rooms.length)];
    const userId = `user_${i}`;
    const userName = `Joiner_${i}`;
    const payload = JSON.stringify({
      room_id: room,
      user_id: userId,
      user_name: userName,
    });
    const res = http.post(`${baseUrl}/api/room/join`, payload, {
      headers: { "Content-Type": "application/json" },
    });
    check(res, { "setup: joined room": (r) => r.status === 200 });
    if (res.status === 200) {
      joiners.push({ user_id: userId, user_name: userName, room_id: room });
    }
  }

  console.log(`✅ Setup done. Rooms: ${JSON.stringify(rooms)}`);
  console.log(`✅ Joined users: ${joiners.length}`);
  return { rooms, joiners };
}

export function createRoom(data) {
  const userId = `creator_${__VU}`;
  const userName = `Creator_${__VU}`;
  const res = http.post(
    `${baseUrl}/api/room/create?user_id=${userId}&user_name=${userName}`
  );
  check(res, { "creator: room created": (r) => r.status === 200 });
  sleep(1);
}

export function joinRoom(data) {
  const { rooms } = data;
  const room = rooms[Math.floor(Math.random() * rooms.length)];
  const userId = `user_${__VU}`;
  const userName = `Joiner_${__VU}`;
  const payload = JSON.stringify({
    room_id: room,
    user_id: userId,
    user_name: userName,
  });
  const res = http.post(`${baseUrl}/api/room/join`, payload, {
    headers: { "Content-Type": "application/json" },
  });
  check(res, { "joined room": (r) => r.status === 200 });
  sleep(1);
}

export function addSong(data) {
  const { joiners } = data;
  const user = joiners[Math.floor(Math.random() * joiners.length)];

  if (!user) {
    console.warn(`[WARN] No valid user found for addSong`);
    return;
  }

  // ⭐ 修改：使用大的 video_id 範圍（1000-11000）避免被預加載
  // 預加載只會預加載基於 current_song 的 base_num + 1 到 5
  // 所以用大數字的 id 確保是首次下載
  const videoId = `${10000 + Math.floor(Math.random() * 100000)}_song`;
  const payload = JSON.stringify({
    video_id: videoId,
    title: `Mock Song ${videoId}`,
    channel: "Mock Artist",
    duration: 200,
    thumbnail: "https://picsum.photos/200",
  });

  const res = http.post(
    `${baseUrl}/api/room/${user.room_id}/queue/add?user_id=${user.user_id}&user_name=${user.user_name}`,
    payload,
    { headers: { "Content-Type": "application/json" } }
  );

  check(res, { "song added": (r) => r.status === 200 });
  sleep(1);
}

export function checkPlaybackReady(data) {
  const { rooms } = data;
  const room = rooms[Math.floor(Math.random() * rooms.length)];

  // 取得 queue 資料
  const queueRes = http.get(`${baseUrl}/api/room/${room}/queue`);
  const queueJson = queueRes.json();

  if (!queueJson.current_song && queueJson.queue.length === 0) {
    console.warn(`⚠️ Room ${room} has no songs, skip`);
    return;
  }

  const targetVideoId = queueJson.current_song.video_id;
  console.log(`🎧 Checking playback latency for ${targetVideoId} in room ${room}`);

  // ===== 修正：使用新的 video_id 確保是首次下載 =====
  // 不再使用預先存在的 video_id，而是從新添加的歌曲開始測試
  
  // 第一次呼叫 status - 啟動計時器
  let res = http.get(
    `${baseUrl}/api/audio/${targetVideoId}/status?room_id=${room}`
  );
  check(res, {
    "first status call": (r) => r.status === 200,
  });

  let latency = null;
  let ready = false;

  // 輪詢直到 ready
  for (let i = 0; i < 60; i++) {
    const statusRes = http.get(
      `${baseUrl}/api/audio/${targetVideoId}/status?room_id=${room}`
    );
    const json = statusRes.json();

    if (json.status === "ready") {
      ready = true;
      latency = json.latency;
      console.log(
        `✅ ${targetVideoId} ready in ${latency.toFixed(3)}s (room ${room})`
      );
      break;
    } else if (json.status === "downloading") {
      console.log(
        `⏳ ${targetVideoId} downloading... (${i + 1}s, elapsed: ${json.elapsed_time?.toFixed(3) || 'N/A'}s)`
      );
      sleep(1);
    } else {
      console.warn(`⚠️ Unexpected response: ${statusRes.body}`);
      sleep(1);
    }
  }

  check(ready, {
    "song ready": (r) => r === true,
  });

  if (ready && latency !== null) {
    check(latency, {
      "latency recorded": (r) => r > 0,
      "latency reasonable": (r) => r < 20, // 應該在 3-7 秒之間
    });
  }

  if (!ready) {
    console.error(`❌ ${targetVideoId} not ready after 60s`);
  }
}