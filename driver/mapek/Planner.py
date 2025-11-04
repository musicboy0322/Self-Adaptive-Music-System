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
    
    def _decide_action(self, analysis_result, config, svc):
        if not analysis_result or "adaptation" not in analysis_result:
            print("Warning: Unexpected behavior")
            return None, None
    
        new_config = copy.deepcopy(config)  # Don't modify original
        adaptations = []
        system_situation = analysis_result["adaptation"]
        overall_utility = analysis_result["overall_utility"]

        print(f'''{svc}: {system_situation}''')
        print(analysis_result["unhealthy_metrics"])

        ## When system situation is healthy
        if system_situation == "healthy":
            return None, None
        ## When system situation is warning
        elif system_situation == "warning":
            new_config = self._adopt_warning_situation(analysis_result["unhealthy_metrics"], new_config, adaptations, svc)
        ## When system situation is unhealthy
        elif system_situation == "unhealthy":
            new_config = self._adopt_unhealthy_situation(analysis_result["unhealthy_metrics"], new_config, adaptations, svc)

        print(config)
        print(new_config)

        old_cpu = (config["requests"]["cpu"] + config["limits"]["cpu"]) / 2
        new_cpu = (new_config["requests"]["cpu"] + new_config["limits"]["cpu"]) / 2
        old_memory = (config["requests"]["memory"] + config["limits"]["memory"]) / 2
        new_memory = (new_config["requests"]["memory"] + new_config["limits"]["memory"]) / 2
        old_replica = config["replica"] 
        new_replica = new_config["replica"]

        # calculate single cost
        cpu_cost = abs((new_cpu - old_cpu) / old_cpu) if old_cpu else 0
        mem_cost = abs((new_memory - old_memory) / old_memory) if old_memory else 0
        replica_cost = abs((new_replica - old_replica) / old_replica) if old_replica else 0
        # calculate overall cost
        total_cost = 0.4 * cpu_cost + 0.4 * mem_cost + 0.2 * replica_cost
        # calculate benifit from the changes in this time
        benefit = 0.5 * ((new_cpu - old_cpu) / old_cpu if old_cpu else 0) + \
                0.5 * ((new_memory - old_memory) / old_memory if old_memory else 0)        
        predicted_utility = min(1.0, overall_utility + benefit)
        # calculate roi
        roi = abs(benefit) / (total_cost + 1e-6)
        

        print(f"{svc} Utility={benefit:.3f}, Cost={total_cost:.3f}, ROI={roi:.2f}")

        if roi == 0:
            print(f"Skipping adaptation for {svc} (Don't have any change between old and new config)")
            return None, None
        elif roi < self.roi_threshold:
            print(f"Skipping adaptation for {svc} (ROI too low: {roi:.2f})")
            return None, None
        else:
            print(f"Proceeding with adaptation for {svc} (ROI: {roi:.2f})")
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

    def _adopt_warning_situation(self, unhealthy_metrics, new_config, adaptations, svc):
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

    def _adopt_unhealthy_situation(self, unhealthy_metrics, new_config, adaptations, svc):
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