import os
import json
import time
import csv
from datetime import datetime

from dotenv import load_dotenv

from mapek.Knowledge import Knowledge
from mapek.Monitor import Monitor
from mapek.Analyzer import Analyzer
from mapek.Planner import Planner
from mapek.Executor import Executor
from utils import init_csv, append_to_csv

def main():
    # Create a CSV file for the dataset
    csv_file = "datasets/cartunes_metrics_dataset.csv"
    if not os.path.exists("datasets"):
        os.mkdir("datasets")

    # Read .env file
    load_dotenv()

    # Initialize parameters
    guid = os.getenv("GUID")
    apikey = os.getenv("APIKEY")
    url = os.getenv("URL")
    sleep = int(os.getenv("SLEEP", "60"))

    # Target service
    service_to_use = [
        "cartunes-app"
    ]

    current_configs = {svc: {"cpu": 500, "memory": 512, "replica": 1} for svc in service_to_use}

    # Metrics settings
    monitor_metrics = [
        # avg
        ("cpu.quota.used.percent", "avg"),
        ("memory.limit.used.percent", "avg"),
        ("net.request.time.in", "avg"),
        # max
        ("net.http.request.time", "max"),
        ("net.request.time.in", "max"),
        ("net.bytes.in", "max"),
        ("net.bytes.out", "max"),
        ("net.bytes.total", "max"),
        ("kubernetes.deployment.replicas.available", "max"),
        # sum
        ("net.request.count.in", "sum"),
        ("net.http.error.count", "sum"),
        ("net.bytes.total", "sum"),
    ]

    analyze_metrics = [
        # Four Golden Signals
        # Latency
        ("net.request.time.in", "avg"),
        ("net.request.time.in", "max"),
        # Traffic
        ("net.request.count.in", "sum"),
        ("net.bytes.total", "sum"),
        # Errors
        ("net.http.error.count", "sum"),
        # Saturation
        ("cpu.quota.used.percent", "avg"),
        ("memory.limit.used.percent", "avg"),
        ("kubernetes.deployment.replicas.available", "max"),
    ]

    # Initialize CSV file
    init_csv(csv_file)
    
    # Initialize components
    knowledge = Knowledge("./mapek/knowledge.json")
    resources = knowledge.get_resources()
    current_configs = {
        svc: {
            "requests": {
                "cpu": resources[svc]["requests"]["cpu"],
                "memory": resources[svc]["requests"]["memory"]
            },
            "limits": {
                "cpu": resources[svc]["limits"]["cpu"],
                "memory": resources[svc]["limits"]["memory"]
            },
            "replica": resources[svc]["replica"],
            "song_quality": resources[svc]["song_quality"],
            "preload_song": resources[svc]["preload_song"],
            "cache_size": resources[svc]["cache_size"]
        }
        for svc in service_to_use
    }

    monitor = Monitor(url, apikey, guid, sleep)
    analyzer = Analyzer(analyze_metrics, service_to_use, knowledge.get_threshold(), knowledge.get_weight())
    planner = Planner(service_to_use, knowledge.get_resource_limitations(), knowledge.get_resources(), knowledge.get_threshold()["roi"])
    executor = Executor()

    print("")
    print("Starting MAPE-K adaptation loop...")
    cycle_count = 0

    # Start monitor and analyze
    while True:
        cycle_count += 1
        print(f"\n=== Adaptation Cycle {cycle_count} ===")
        print("")
        # MONITOR: Collect metrics
        print("[Monitoring Stage]")
        print("Getting metrics from IBM Cloud...")
        print("")
        qos_data = {}
        for metric, agg in monitor_metrics:
            res = monitor.fetch_data_from_ibm(metric, agg)
            if res:
                qos_data[(metric, agg)] = res
            else:
                print(f"Failed to fetch {metric} with {agg} aggregation")
        qoe_data = monitor.fetch_data_from_cartunes()
        print("")
        
        # ANALYZE: Process metrics
        print("[Analyzing Stage]")
        analysis_results = analyzer.process_data(qos_data, qoe_data)
        if len(analysis_results) == 0:
            print("Need to gather more data to continue, preventing from scaling flapping")
            time.sleep(sleep)
            continue

        # PLAN: Generate adaptation decisions
        print("[Planning Stage]")
        decisions, new_configs, system_situations = planner.evaluate_services(analysis_results, current_configs)
        print("")

        # EXECUTE: Apply adaptations
        print("[Executing Stage]")
        if system_situations == "qoe_unhealthy":
            sucess = executor.execute_qoe_plan(decisions, new_configs, system_situations)
        else: 
            success = executor.execute_qos_plan(decisions, current_configs, system_situations)

        if success:
            print("Successfully executed adaptation")
            current_configs = new_configs
        else:
            print("Failed to execute adaptation")

        # KNOWLEDGE: Store data with adaptation information
        timestamp = datetime.now().isoformat()
        append_to_csv(csv_file, timestamp, qos_data, service_to_use)

        # wait for next round
        time.sleep(sleep)

if __name__ == "__main__":
    main()