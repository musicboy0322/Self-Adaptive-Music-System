import json
from collections import deque

import pandas as pd

class Analyzer:
    def __init__(self, analyze_metrics, service_to_use, thresholds, weights):
        self.window_size = 5
        self.metrics = analyze_metrics
        self.services = service_to_use
        
        self.deque_keys = ["cpu_deque", "memory_deque", "latency_avg_deque", "error_rate_deque"]
        self.service_deque = {
            svc: {key: deque(maxlen=self.window_size) for key in self.deque_keys}
            for svc in service_to_use
        }

        self.cpu_threshold_high = thresholds["cpu"]["high"]
        self.cpu_threshold_low = thresholds["cpu"]["low"]
        self.memory_threshold_high = thresholds["memory"]["high"]
        self.memory_threshold_low = thresholds["memory"]["low"]
        self.latency_avg_threshold = thresholds["latency"]["avg"]
        self.latency_max_threshold = thresholds["latency"]["max"]
        self.error_rate_threshold = thresholds["error_rate"]

        self.cpu_weight = weights["cpu"]
        self.memory_weight = weights["memory"]
        self.latency_weight = weights["latency"]
        self.error_rate_weight = weights["error_rate"]

    def _evaluate_metrics(self, svc, cpu, memory, latency_avg, latency_max, request_count, request_per_second, request_byte_total, error_rate, gc_time):
        print(f"""
            CPU: {cpu:.2f}%
            Memory: {memory:.2f}%
            Latency (avg): {latency_avg/1000000:.2f} ms
            Latency (max): {latency_max/1000000:.2f} ms
            Request Count: {request_count:.2f}
            RPS: {request_per_second:.2f}
            Request Byte Total: {request_byte_total*1.024/1000:.2f} KB/s
            Error Rate: {error_rate:.2f}%
            GC Time: {gc_time / 1000:.2f} ms
        """)

        deques = self.service_deque[svc]
        deques["cpu_deque"].append(cpu)
        deques["memory_deque"].append(memory)
        deques["latency_avg_deque"].append(latency_avg/1000000)
        deques["error_rate_deque"].append(error_rate)

        cpu_avg = sum(deques["cpu_deque"]) / len(deques["cpu_deque"])
        memory_avg = sum(deques["memory_deque"]) / len(deques["memory_deque"])
        latency_avg_avg = sum(deques["latency_avg_deque"]) / len(deques["latency_avg_deque"])
        error_rate_avg = sum(deques["error_rate_deque"]) / len(deques["error_rate_deque"])

        unhealthy_metrics = set()
        result = {
            "cpu": cpu_avg,
            "memory": memory_avg,
            "latency_avg": latency_avg_avg,
            "latency_max": latency_max,
            "request_count": request_count,
            "request_per_second": request_per_second,
            "request_byte_total": request_byte_total,
            "error_rate": error_rate_avg,
            "gc_time": gc_time,
            "overall_utility": 0,
            "adaptation": "",
            "unhealthy_metrics": unhealthy_metrics
        }


        confidence = len(deques["cpu_deque"]) / self.window_size
        if confidence >= 0.8:
            # analyze global health
            cpu_utility = self._normalize_high_is_good(self.cpu_threshold_low, self.cpu_threshold_high, cpu_avg)
            memory_utility = self._normalize_high_is_good(self.memory_threshold_low, self.memory_threshold_high, memory_avg)
            latency_utility = self._normalize_low_is_good(self.latency_avg_threshold, latency_avg_avg/1000000)
            error_rate_utility = self._normalize_low_is_good(self.error_rate_threshold, error_rate_avg)
            overall_utility = cpu_utility * self.cpu_weight + memory_utility * self.memory_weight + latency_utility * self.latency_weight + error_rate_utility * self.error_rate_weight
            result["overall_utility"] = overall_utility

            # analyze local health
            if cpu_avg > self.cpu_threshold_high:
                unhealthy_metrics.add("cpu_high")
            elif cpu_avg < self.cpu_threshold_low:
                unhealthy_metrics.add("cpu_low")

            if memory_avg > self.memory_threshold_high:
                unhealthy_metrics.add("memory_high")
            elif memory_avg < self.memory_threshold_low:
                unhealthy_metrics.add("memory_low")
            
            if latency_avg_avg > self.latency_avg_threshold:
                unhealthy_metrics.add("latency_avg_high")
            
            if error_rate_avg > self.error_rate_threshold:
                unhealthy_metrics.add("error_rate_high")

            # analyze system health
            if overall_utility >= 0.8 and len(unhealthy_metrics) == 0:
                # everything good
                result["adaptation"] = "healthy"
            elif overall_utility < 0.5 or len(unhealthy_metrics) >= 2:
                # need to modify system's baseline and headroom
                result["adaptation"] = "unhealthy"
            else:
                # need to modify system's baseline
                result["adaptation"] = "warning"
            return result
        else:
            return None

    def _create_dataframe(self, data):
        return pd.DataFrame([{
            "timestamp": e['t'], "service": e['d'][0], "value": e['d'][1]
        } for e in data["data"]])

    def process_data(self, data_dict):
        outputs = {svc: {} for svc in self.services}
        analysis_results = {}

        for idx, (metric_id, aggregation) in enumerate(self.metrics):
            data = data_dict.get((metric_id, aggregation))
            if data is None:
                print(f"No data for metric {metric_id} with aggregation {aggregation}")
                continue

            df = self._create_dataframe(data)
            df_filtered = df[df['service'].isin(self.services)]
            avg_values = df_filtered.groupby('service')['value'].mean()

            metric_name = f"{metric_id}_{aggregation}"

            for svc, val in avg_values.items():
                outputs[svc][metric_name] = val

        for svc, metric_values in outputs.items():
            print("//////////////////////////////////////////")
            print(f"Service: {svc}")

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
            gc_time = metric_values.get("jvm.gc.global.time_avg", 0)

            result = self._evaluate_metrics(svc, cpu, memory, latency_avg, latency_max, request_count, request_per_second, request_byte_total, error_rate, gc_time)
            if result != None:
                result["service"] = svc
                analysis_results[svc] = result

        return analysis_results

    def _normalize_high_is_good(self, low, high, value):
        return (value - low) / (high - low)
    
    def _normalize_low_is_good(self, high, value):
        return max(0.0, 1.0 - min(value / high, 1.0))
    