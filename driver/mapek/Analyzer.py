import json
from collections import deque
import pandas as pd


# =======================================================
#   ANALYZER — QoS (utility-based) + QoE (rule-based)
# =======================================================
class Analyzer:
    def __init__(self, analyze_metrics, service_to_use, thresholds, weights):
        self.window_size = 5
        self.metrics = analyze_metrics
        self.services = service_to_use

        # sliding windows
        self.deque_keys = [
            "cpu_deque", "memory_deque", "latency_avg_deque", "error_rate_deque",
            "disk_usage", "cache_hit_ratio", "avg_playback_latency", "avg_download_time"
        ]
        self.service_deque = {
            svc: {key: deque(maxlen=self.window_size) for key in self.deque_keys}
            for svc in service_to_use
        }

        # QoS thresholds
        self.cpu_threshold_high = thresholds["cpu"]["high"]
        self.cpu_threshold_low = thresholds["cpu"]["low"]
        self.memory_threshold_high = thresholds["memory"]["high"]
        self.memory_threshold_low = thresholds["memory"]["low"]
        self.latency_avg_threshold = thresholds["latency"]["avg"]
        self.latency_max_threshold = thresholds["latency"]["max"]
        self.error_rate_threshold = thresholds["error_rate"]

        # QoS utility weights
        self.cpu_weight = weights["cpu"]
        self.memory_weight = weights["memory"]
        self.latency_weight = weights["latency"]
        self.error_rate_weight = weights["error_rate"]

        # QoE thresholds
        self.avg_playback_latency_threshold_high = thresholds["avg_playback_latency"]["high"]
        self.avg_playback_latency_threshold_low = thresholds["avg_playback_latency"]["low"]
        self.avg_download_time_threshold_high = thresholds["avg_download_time"]["high"]
        self.avg_download_time_threshold_low = thresholds["avg_download_time"]["low"]
        self.cache_hit_ratio_threshold_low = thresholds["cache_hit_ratio"]["low"]
        self.disk_usage_threshold = thresholds["disk_usage"]


    # ===============================
    #   Metric Evaluation
    # ===============================
    def _evaluate_metrics(self, svc, cpu, memory, latency_avg, latency_max, request_count,
                          request_per_second, request_byte_total, error_rate,
                          available_replicas, disk_usage, cache_hit_ratio,
                          avg_playback_latency, avg_download_time):

        deques = self.service_deque[svc]

        # QoS windows
        deques["cpu_deque"].append(cpu)
        deques["memory_deque"].append(memory)
        deques["latency_avg_deque"].append(latency_avg / 1_000_000)
        deques["error_rate_deque"].append(error_rate)

        cpu_avg = sum(deques["cpu_deque"]) / len(deques["cpu_deque"])
        memory_avg = sum(deques["memory_deque"]) / len(deques["memory_deque"])
        latency_avg_avg = sum(deques["latency_avg_deque"]) / len(deques["latency_avg_deque"])
        error_rate_avg = sum(deques["error_rate_deque"]) / len(deques["error_rate_deque"])

        # QoE windows
        deques["disk_usage"].append(disk_usage)
        deques["cache_hit_ratio"].append(cache_hit_ratio)
        deques["avg_playback_latency"].append(avg_playback_latency)
        deques["avg_download_time"].append(avg_download_time)

        disk_usage_avg = sum(deques["disk_usage"]) / len(deques["disk_usage"])
        cache_hit_ratio_avg = sum(deques["cache_hit_ratio"]) / len(deques["cache_hit_ratio"])
        avg_playback_latency_avg = sum(deques["avg_playback_latency"]) / len(deques["avg_playback_latency"])
        avg_download_time_avg = sum(deques["avg_download_time"]) / len(deques["avg_download_time"])

        qos_unhealthy = set()
        qoe_unhealthy = set()

        result = {
            "cpu": cpu_avg,
            "memory": memory_avg,
            "latency_avg": latency_avg_avg,
            "latency_max": latency_max,
            "request_count": request_count,
            "request_per_second": request_per_second,
            "request_byte_total": request_byte_total,
            "error_rate": error_rate_avg,
            "available_replicas": available_replicas,
            "disk_usage": disk_usage_avg,
            "cache_hit_ratio": cache_hit_ratio_avg,
            "avg_playback_latency": avg_playback_latency_avg,
            "avg_download_time": avg_download_time_avg,
            "qos_overall_utility": 0,
            "adaptation": [],
            "qos_unhealthy_metrics": qos_unhealthy,
            "qoe_unhealthy_metrics": qoe_unhealthy
        }

        confidence = len(deques["cpu_deque"]) / self.window_size
        
        #if confidence < 0.8:
        #    return None

        # ===============================
        # QoS Utility
        # ===============================
        cpu_util = self._normalize_high_is_good(self.cpu_threshold_low, self.cpu_threshold_high, cpu_avg)
        mem_util = self._normalize_high_is_good(self.memory_threshold_low, self.memory_threshold_high, memory_avg)
        latency_util = self._normalize_low_is_good(self.latency_avg_threshold, latency_avg_avg)
        error_util = self._normalize_low_is_good(self.error_rate_threshold, error_rate_avg)

        qos_utility = (
            cpu_util * self.cpu_weight +
            mem_util * self.memory_weight +
            latency_util * self.latency_weight +
            error_util * self.error_rate_weight
        )
        result["qos_overall_utility"] = qos_utility

        # ===============================
        # Local QoS health
        # ===============================
        if cpu_avg > self.cpu_threshold_high:
            qos_unhealthy.add("cpu_high")
        elif cpu_avg < self.cpu_threshold_low:
            qos_unhealthy.add("cpu_low")

        if memory_avg > self.memory_threshold_high:
            qos_unhealthy.add("memory_high")
        elif memory_avg < self.memory_threshold_low:
            qos_unhealthy.add("memory_low")

        if latency_avg_avg > self.latency_avg_threshold:
            qos_unhealthy.add("latency_avg_high")

        if error_rate_avg > self.error_rate_threshold:
            qos_unhealthy.add("error_rate_high")

        if available_replicas <= 0:
            qos_unhealthy.add("no_replicas")

        # ===============================
        # Local QoE health
        # ===============================
        if avg_playback_latency_avg > self.avg_playback_latency_threshold_high:
            qoe_unhealthy.add("playback_latency_high")
        elif avg_playback_latency_avg < self.avg_playback_latency_threshold_low:
            qoe_unhealthy.add("playback_latency_low")

        if avg_download_time_avg > self.avg_download_time_threshold_high:
            qoe_unhealthy.add("download_time_high")
        elif avg_download_time_avg < self.avg_download_time_threshold_low:
            qoe_unhealthy.add("download_time_low")

        if cache_hit_ratio_avg < self.cache_hit_ratio_threshold_low:
            qoe_unhealthy.add("cache_hit_low")

        if disk_usage_avg > self.disk_usage_threshold:
            qoe_unhealthy.add("disk_usage_high")

        # ===============================
        #   Adaptation flags
        # ===============================
        if "no_replicas" in qos_unhealthy:
            result["adaptation"].append("self_heal")

        if qoe_unhealthy:
            result["adaptation"].append("qoe_unhealthy")
        else:
            result["adaptation"].append("qoe_healthy")

        if qos_utility >= 0.8 and len(qos_unhealthy) == 0:
            result["adaptation"].append("qos_healthy")
        elif qos_utility < 0.5 or len(qos_unhealthy) >= 2:
            result["adaptation"].append("qos_unhealthy")
        else:
            result["adaptation"].append("qos_warning")

        return result

    def _create_dataframe(self, data):
        return pd.DataFrame([{
            "timestamp": e['t'], "service": e['d'][0], "value": e['d'][1]
        } for e in data["data"]])

    def process_data(self, qos_data, qoe_data):
        outputs = {svc: {} for svc in self.services}
        analysis_results = {}   
        for (metric_id, aggregation) in self.metrics:
            data = qos_data.get((metric_id, aggregation))
            if data is None:
                print(f"No data for metric {metric_id} with aggregation {aggregation}")
                continue
            try:
                df = self._create_dataframe(data)
                df_filtered = df[df['service'].isin(self.services)]
                avg_values = df_filtered.groupby('service')['value'].mean()

                metric_name = f"{metric_id}_{aggregation}"

                for svc, val in avg_values.items():
                    outputs[svc][metric_name] = val
            except:
                print("Don't have data now. Please first request the server by test.js")

        for svc, metric_values in outputs.items():
            print(f"Service: {svc}")
            ## QoS metrcis
            # Latency
            latency_avg = metric_values.get("net.request.time.in_avg", 0)
            latency_max = metric_values.get("net.request.time.in_max", 0)
            # Traffic
            request_count = metric_values.get("net.request.count.in_sum", 0)
            request_per_second = metric_values.get("net.request.count.in_sum", 0) / 10
            request_byte_total = metric_values.get("net.bytes.total_sum", 0)
            # Errors
            errors = metric_values.get("net.http.error.count_sum", 0)
            error_rate = errors / request_count if request_count else 0
            # Saturation
            cpu = metric_values.get("cpu.quota.used.percent_avg", 0)
            memory = metric_values.get("memory.limit.used.percent_avg", 0)
            # Other
            available_replicas = metric_values.get("kubernetes.deployment.replicas.available_max", 0)

            ## QoE metrics
            cache_hit_ratio = None
            disk_usage = qoe_data["disk_usage"]
            avg_playback_latency = qoe_data["avg_playback_latency"] 
            avg_download_time = qoe_data["avg_download_time"]
            if qoe_data["cache_hit_ratio"][0] or qoe_data["cache_hit_ratio"][1] == 0:
                cache_hit_ratio = 0
            else:
                cache_hit_ratio = (qoe_data["cache_hit_ratio"][0] / (qoe_data["cache_hit_ratio"][0] + qoe_data["cache_hit_ratio"][1])) * 100

            result = self._evaluate_metrics(svc, cpu, memory, latency_avg, latency_max, request_count, request_per_second, 
                                            request_byte_total, error_rate, available_replicas, disk_usage, cache_hit_ratio,
                                            avg_playback_latency, avg_download_time)
            if result != None:
                result["service"] = svc
                analysis_results[svc] = result

        return analysis_results
    
    # ===============================
    def _normalize_high_is_good(self, low, high, value):
        return (value - low) / (high - low)

    def _normalize_low_is_good(self, high, value):
        return max(0.0, 1.0 - min(value / high, 1.0))
