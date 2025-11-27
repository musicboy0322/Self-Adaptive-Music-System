import copy

class Planner:
    def __init__(self, service_to_use, resources_limitations, resources, roi):
        self.min_replica = resources_limitations["single"]["min_replica"]
        self.max_replica = resources_limitations["single"]["max_replica"]
        self.min_cpu = resources_limitations["single"]["min_cpu"]
        self.max_cpu = resources_limitations["single"]["max_cpu"] 
        self.min_memory = resources_limitations["single"]["min_memory"]
        self.max_memory = resources_limitations["single"]["max_memory"]
        self.roi_threshold = roi
        self.baseline_resources = resources

    def _decide_action(self, analysis_result, config, svc):
        if not analysis_result or "adaptation" not in analysis_result:
            print("Warning: Unexpected behavior")
            return None, None

        system_situation = ""
        base_adaptation = analysis_result["adaptation"]
        qos_unhealthy_metrics = analysis_result["qos_unhealthy_metrics"]
        qoe_unhealthy_metrics = analysis_result["qoe_unhealthy_metrics"]
        qos_overall_utility = analysis_result["qos_overall_utility"]
        qoe_fixed = False

        if "self_heal" in base_adaptation:
            # Level 2: catastrophic (no replicas)
            if "no_replicas" in qos_unhealthy_metrics:
                system_situation = "self_heal_hard"
            else:
                # Level 1: try restart/scale first
                system_situation = "self_heal_soft"

        print(f"{svc}: situation={system_situation}")

        new_config = copy.deepcopy(config)
        adaptations = []

        # SELF-HEAL: always act, ROI does not apply
        if system_situation in ("self_heal_soft", "self_heal_hard"):
            print(f"{svc}: triggering {system_situation}.")
            return system_situation, copy.deepcopy(config)

        if "qoe_unhealthy" in base_adaptation:
            system_situation = "qoe_unhealthy"
            qoe_fixed = True
            new_config = self._adopt_qoe_unhealthy_situation(qoe_unhealthy_metrics, new_config, adaptations, svc)
            print(f"{svc}: QoE adjusted; continuing to check QoS...")

        # WARNING / UNHEALTHY: self-optimizing logic with ROI
        if "qos_warning" in base_adaptation:
            system_situation = "qos_warning"
            new_config = self._adopt_qos_warning_situation(qos_unhealthy_metrics, new_config, adaptations, svc)
        elif "qos_unhealthy" in base_adaptation: 
            system_situation = "qos_unhealthy"
            new_config = self._adopt_qos_unhealthy_situation(qos_unhealthy_metrics, new_config, adaptations, svc)

        print("Old config:", config)
        print("New config:", new_config)

        if qoe_fixed and system_situation == "qoe_unhealthy":
            return system_situation, new_config
        
        if "qos_healthy" in base_adaptation:
            print(f"{svc}: QoS healthy → no action.")
            return None, None

        old_cpu = (config["requests"]["cpu"] + config["limits"]["cpu"]) / 2
        cpu_now = (new_config["requests"]["cpu"] + new_config["limits"]["cpu"]) / 2
        latency_now = analysis_result["latency_avg"]

        candidates = []
        for delta in [-250, 0, 250]:
            new_cpu = max(self.min_cpu, min(self.max_cpu, cpu_now + delta))

            cfg = copy.deepcopy(new_config)

            cfg["song_quality"] = new_config["song_quality"]
            cfg["cache_size"] = new_config["cache_size"]
            cfg["preload_song"] = new_config["preload_song"]

            cfg["limits"]["cpu"] = new_cpu
            cfg["requests"]["cpu"] = new_cpu

            latency_after = latency_now * (cpu_now / new_cpu)

            candidates.append({
                "cpu_after": new_cpu,
                "latency_after": latency_after,
                "config": cfg
            })

        pareto = self._pareto_frontier(candidates)
        best = None
        best_roi = -1

        old_memory = (config["requests"]["memory"] + config["limits"]["memory"]) / 2
        old_replica = config["replica"]

        for item in pareto:
            cfg = item["config"]
            new_cpu = item["cpu_after"]
            new_memory = new_config["requests"]["memory"]
            new_replica = new_config["replica"]

            cpu_cost = abs((new_cpu - old_cpu) / old_cpu) if old_cpu else 0
            mem_cost = abs((new_memory - old_memory) / old_memory) if old_memory else 0
            replica_cost = abs((new_replica - old_replica) / old_replica) if old_replica else 0
            total_cost = 0.4 * cpu_cost + 0.4 * mem_cost + 0.2 * replica_cost

            benefit = (cpu_now - new_cpu) / old_cpu if old_cpu else 0
            roi = abs(benefit) / (total_cost + 1e-6)

            if roi > best_roi:
                best_roi = roi
                best = cfg

        if best is not None:
            new_config = best

        new_cpu = (new_config["requests"]["cpu"] + new_config["limits"]["cpu"]) / 2
        new_memory = (new_config["requests"]["memory"] + new_config["limits"]["memory"]) / 2
        new_replica = new_config["replica"]

        cpu_cost = abs((new_cpu - old_cpu) / old_cpu) if old_cpu else 0
        mem_cost = abs((new_memory - old_memory) / old_memory) if old_memory else 0
        replica_cost = abs((new_replica - old_replica) / old_replica) if old_replica else 0

        total_cost = 0.4 * cpu_cost + 0.4 * mem_cost + 0.2 * replica_cost
        benefit = 0.5 * ((new_cpu - old_cpu) / old_cpu if old_cpu else 0) + \
                0.5 * ((new_memory - old_memory) / old_memory if old_memory else 0)
        predicted_utility = min(1.0, qos_overall_utility + benefit)

        roi = abs(benefit) / (total_cost + 1e-6)

        print(f"{svc} ROI={roi:.2f}, PredictedUtility={predicted_utility:.3f}")

        if roi < self.roi_threshold:
            print(f"{svc}: ROI too low → skip QoS optimization.")
            return None, None

        return system_situation, new_config

    def evaluate_services(self, analysis_results, current_configs):
        decisions = {}
        new_configs = current_configs.copy()
        system_situations = {}
        
        for svc, result in analysis_results.items():
            system_situation, new_config = self._decide_action(result, current_configs[svc], svc)
            if new_config:
                decisions[svc] = new_config
                new_configs[svc] = new_config
                system_situations[svc] = system_situation
            else:
                decisions[svc] = None
        
        return decisions, new_configs, system_situations

    def _adopt_qos_warning_situation(self, unhealthy_metrics, new_config, adaptations, svc):
        ## Vertical Scale Up & Scale Down
        # situation of increasing cpu
        if "cpu_high" in unhealthy_metrics and "latency_avg_high" in unhealthy_metrics:
            new_config["limits"]["cpu"] = min(new_config["limits"]["cpu"] + 250, self.max_cpu)
            adaptations.append("increase_cpu")

        # situation of increasing memory
        if "memory_high" in unhealthy_metrics:
            new_config["limits"]["memory"] = min(new_config["limits"]["memory"] + 256, self.max_memory)
            adaptations.append("increase_memory")

        # situation of decreasing CPU
        if "cpu_low" in unhealthy_metrics:
            new_config["limits"]["cpu"] = max(new_config["limits"]["cpu"] - 250, self.min_cpu)
            adaptations.append("decrease_cpu")
        
        # situation of decreasing memory
        if "memory_low" in unhealthy_metrics:
            new_config["limits"]["memory"] = max(new_config["limits"]["memory"] - 256, self.min_memory)
            adaptations.append("decrease_memory")

        ## Horizontal Scale Up & Scale Down
        # situation of increasing replica
        if ((new_config["limits"]["cpu"] >= self.max_cpu or new_config["limits"]["memory"] >= self.max_memory) and 
            ("latency_avg_high" in unhealthy_metrics or "error_rate_high" in unhealthy_metrics)):
            new_config["replica"] = min(new_config["replica"] + 1, self.max_replica)
            adaptations.append("increase_replica")

        # situation of decreasing replica
        if "cpu_low" in unhealthy_metrics and "memory_low" in unhealthy_metrics:
            new_config["replica"] = max(new_config["replica"] - 1, self.min_replica)
            adaptations.append("decrease_replica")
        
        return new_config

    def _adopt_qos_unhealthy_situation(self, unhealthy_metrics, new_config, adaptations, svc):
        ## Vertical Scale Up & Scale Down
        # situation of increasing cpu
        if "cpu_high" in unhealthy_metrics and "latency_avg_high" in unhealthy_metrics:
            new_config["requests"]["cpu"] = min(new_config["requests"]["cpu"] + 250, self.max_cpu)
            new_config["limits"]["cpu"] = min(new_config["limits"]["cpu"] + 250, self.max_cpu)
            adaptations.append("increase_cpu")

        # situation of increasing memory
        if "memory_high" in unhealthy_metrics:
            new_config["requests"]["memory"] = min(new_config["requests"]["memory"] + 256, self.max_memory)
            new_config["limits"]["memory"] = min(new_config["limits"]["memory"] + 256, self.max_memory)
            adaptations.append("increase_memory")

        # situation of decreasing CPU
        if "cpu_low" in unhealthy_metrics:
            new_config["requests"]["cpu"] = max(new_config["requests"]["cpu"] - 250, self.min_cpu)
            new_config["limits"]["cpu"] = max(new_config["limits"]["cpu"] - 250, self.min_cpu)
            adaptations.append("decrease_cpu")
        
        # situation of decreasing memory
        if "memory_low" in unhealthy_metrics:
            new_config["requests"]["memory"] = max(new_config["requests"]["memory"] - 256, self.min_memory)
            new_config["limits"]["memory"] = max(new_config["limits"]["memory"] - 256, self.min_memory)
            adaptations.append("decrease_memory")

        ## Horizontal Scale Up & Scale Down
        # situation of increasing replica
        if (("latency_avg_high" in unhealthy_metrics or "error_rate_high" in unhealthy_metrics) and 
            ("cpu_high" in unhealthy_metrics or "memory_high" in unhealthy_metrics)):
            new_config["replica"] = min(new_config["replica"] + 1, self.max_replica)
            adaptations.append("increase_replica")

        # situation of decreasing replica
        if "cpu_low" in unhealthy_metrics and "memory_low" in unhealthy_metrics:
            new_config["replica"] = max(new_config["replica"] - 1, self.min_replica)
            adaptations.append("decrease_replica")
        
        return new_config
    
    def _adopt_qoe_unhealthy_situation(self, unhealthy_metrics, new_config, adaptations, svc):
        # situation of decreasing song quality
        if "playback_latency_high" in unhealthy_metrics and "download_time_high" in unhealthy_metrics:
            new_config["song_quality"] = max(new_config["song_quality"] - 1, 1)

        # situation of increasing song quality
        if "playback_latency_low" in unhealthy_metrics and "download_time_low" in unhealthy_metrics:
            new_config["song_quality"] = min(new_config["song_quality"] + 1, 3)
        
        # situation of decreasing cache size
        if "cache_hit_high" in unhealthy_metrics:
            new_config["cache_size"] = new_config["cache_size"] - 100
        
        # situation of increasing cache size
        if "cache_hit_low" in unhealthy_metrics:
            new_config["cache_size"] = new_config["cache_size"] + 500
                
        # situation of decreasing preload song
        if "download_time_high" in unhealthy_metrics and "cache_hit_low" in unhealthy_metrics:
            new_config["preload_song"] = max(new_config["preload_song"] - 2, 0)
        
        # situation of increasing preload song
        if "download_time_low" in unhealthy_metrics:
            new_config["preload_song"] = min(new_config["preload_song"] + 2, 10)
        
        return new_config
    
    @staticmethod
    def _pareto_frontier(candidates):
        frontier = []
        for i, c1 in enumerate(candidates):
            dominated = False
            for j, c2 in enumerate(candidates):
                if i == j:
                    continue
                if ((c2["cpu_after"] <= c1["cpu_after"]) and
                    (c2["latency_after"] <= c1["latency_after"]) and
                    ((c2["cpu_after"] < c1["cpu_after"]) or 
                    (c2["latency_after"] < c1["latency_after"]))):
                    dominated = True
                    break
            if not dominated:
                frontier.append(c1)
        return frontier