import subprocess
import os
import datetime

class Executor:
    def __init__(self):
        self.backup_dir = "./backup"
        os.makedirs(self.backup_dir, exist_ok=True)

    def _run(self, command):
        res = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return res

    def _dry_run(self, svc):
        cmd = f"oc get deploy {svc} >/dev/null 2>&1"
        res = self._run(cmd)
        if res.returncode == 0:
            print(f"[DRY-RUN][OK] {svc} can be safely updated.")
            return True
        else:
            print(f"[DRY-RUN][ERROR] {svc} verification failed:\n{res.stderr}")
            return False

    def _backup(self, svc):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.backup_dir}/{svc}_{timestamp}.yaml"
        backup_cmd = f"oc get deploy {svc} -o yaml > {backup_path}"
        backup_res = subprocess.run(backup_cmd, shell=True)
        if backup_res.returncode == 0:
            print(f"[BACKUP] {svc} saved to {backup_path}")
            return backup_path
        else:
            print(f"[BACKUP][WARNING] Failed to backup {svc}.")
            return None

    def _rollback(self, svc, backup_path):
        if not backup_path or not os.path.exists(backup_path):
            print(f"[ROLLBACK][ERROR] No valid backup found for {svc}.")
            return
        rollback_cmd = f"oc apply -f {backup_path}"
        res = self._run(rollback_cmd)
        if res.returncode == 0:
            print(f"[ROLLBACK][OK] {svc} restored from backup.")
        else:
            print(f"[ROLLBACK][FAIL] {svc} rollback failed:\n{res.stderr}")

    def execute_plan(self, plan, configs, system_situations):
        print("======== Starting Atomic Adaptation Transaction ========")
        success = True
        backups = {}

        print("\n[STEP 1] Dry-run verification for all services...")
        for svc, adaptation in plan.items():
            if not adaptation:
                continue
            if not self._dry_run(svc):
                print(f"[ABORT] {svc} verification failed. Transaction aborted.")
                return False

        print("\n[STEP 2] Backup & Apply changes...")
        for svc, adaptation in plan.items():
            if not adaptation:
                continue

            mode = system_situations[svc]
            backups[svc] = self._backup(svc)
            print(f"Executing adaptation for {svc}...")

            # Level 2: HARD SELF-HEAL – full reset with deployment.sh
            if mode == "self_heal_hard":
                print(f"[SELF-HEAL HARD] Running full redeployment script for {svc}...")
                command = "bash deployment.sh"
                res = self._run(command)

                if res.returncode == 0:
                    print("[SELF-HEAL HARD] Full redeployment succeeded.")
                    print(res.stdout)
                else:
                    success = False
                    print("[SELF-HEAL HARD][ERROR] Redeployment failed:")
                    print(res.stderr)
                break

            # Level 1: SOFT SELF-HEAL – restart and ensure replicas
            elif mode == "self_heal_soft":
                replica = max(adaptation.get("replica", 1), 1)
                command = (
                    f"oc rollout restart deployment/{svc} && "
                    f"oc scale deployment/{svc} --replicas={replica}"
                )
                res = self._run(command)
                if res.returncode == 0:
                    print(
                        f"[SELF-HEAL SOFT] {svc} restarted and scaled to {replica} replicas."
                    )
                    print(res.stdout)
                else:
                    success = False
                    print(f"[SELF-HEAL SOFT][ERROR] {svc} failed:\n{res.stderr}")
                break

            elif mode == "warning":
                cpu_limits = adaptation["limits"]["cpu"]
                memory_limits = adaptation["limits"]["memory"]
                replica = adaptation["replica"]
                command = (
                    f"oc set resources deployment/{svc} "
                    f"--limits=cpu={cpu_limits}m,memory={memory_limits}Mi && "
                    f"oc scale deployment/{svc} --replicas={replica}"
                )

                res = self._run(command)
                if res.returncode == 0:
                    if cpu_limits != configs[svc]["limits"]["cpu"]:
                        print(f"CPU is changed from {configs[svc]['limits']['cpu']} to {cpu_limits} for {svc}")
                    if memory_limits != configs[svc]["limits"]["memory"]:
                        print(f"Memory is changed from {configs[svc]['limits']['memory']} to {memory_limits} for {svc}")
                    if replica != configs[svc]["replica"]:
                        print(f"Replica is changed from {configs[svc]['replica']} to {replica} for {svc}")
                    print(res.stdout)
                else:
                    success = False
                    print(f"{svc}: Adaptation failed with error:")
                    print(res.stderr)
                    break
            elif mode == "unhealthy":
                cpu_requests = adaptation["requests"]["cpu"]
                cpu_limits = adaptation["limits"]["cpu"]
                memory_requests = adaptation["requests"]["memory"]
                memory_limits = adaptation["limits"]["memory"]
                replica = adaptation["replica"]
                command = (
                    f"oc set resources deployment/{svc} "
                    f"--requests=cpu={cpu_requests}m,memory={memory_requests}Mi "
                    f"--limits=cpu={cpu_limits}m,memory={memory_limits}Mi && "
                    f"oc scale deployment/{svc} --replicas={replica}"
                )

                res = self._run(command)
                if res.returncode == 0:
                    if cpu_limits != configs[svc]["limits"]["cpu"]:
                        print(f"CPU is changed from {configs[svc]['limits']['cpu']} to {cpu_limits} for {svc}")
                    if cpu_requests != configs[svc]["requests"]["cpu"]:
                        print(f"CPU is changed from {configs[svc]['requests']['cpu']} to {cpu_requests} for {svc}")
                    if memory_limits != configs[svc]["limits"]["memory"]:
                        print(f"Memory is changed from {configs[svc]['limits']['memory']} to {memory_limits} for {svc}")
                    if memory_requests != configs[svc]["requests"]["memory"]:
                        print(f"Memory is changed from {configs[svc]['requests']['memory']} to {memory_requests} for {svc}")
                    if replica != configs[svc]["replica"]:
                        print(f"Replica is changed from {configs[svc]['replica']} to {replica} for {svc}")
                    print(res.stdout)
                else:
                    success = False
                    print(f"{svc}: Adaptation failed with error:")
                    print(res.stderr)
                    break

        if not success:
            print("\n[STEP 3] Rolling back all previously modified services...")
            for rollback_svc, backup_file in backups.items():
                self._rollback(rollback_svc, backup_file)
            print("[TRANSACTION][ABORTED] All changes reverted.")
            return False

        print("\n[STEP 3] All services successfully updated.")
        print("[TRANSACTION][SUCCESS] Atomic adaptation completed.")
        return True