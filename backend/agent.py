import requests
import time
import uuid
import subprocess
import os
from pynvml import *

try:
    nvmlInit()
    handle = nvmlDeviceGetHandleByIndex(0)
    gpu_name = nvmlDeviceGetName(handle)
    vram_total = nvmlDeviceGetMemoryInfo(handle).total / (1024**3)
except Exception as e:
    gpu_name = "Unknown GPU"
    vram_total = 0.0

NODE_ID = f"node-{uuid.uuid4().hex[:6]}"
SERVER_URL = "http://localhost:8000"

def start_agent():
    print(f"--- Aperture Agent Started ---")
    print(f"Targeting: {gpu_name} ({vram_total:.2f} GB)")
    print(f"Node ID: {NODE_ID}")
    print("Listening for tasks... (Press Ctrl+C to stop)\n")

    payload = {
        "node_id": NODE_ID,
        "gpu_name": gpu_name,
        "vram_total": round(vram_total, 2),
        "status": "ONLINE"
    }

    while True:
        try:
            # 1. Отправляем сигнал "Я жив"
            requests.post(f"{SERVER_URL}/register_node", json=payload)
            
            # 2. Запрашиваем задачу
            task_res = requests.get(f"{SERVER_URL}/get_task").json()
            
            if task_res.get("task_id"):
                task_id = task_res["task_id"]
                code = task_res["code"]
                print(f"[*] Task caught: {task_id}. Executing locally...")
                
                # Сохраняем код во временный файл
                with open("temp_task.py", "w", encoding="utf-8") as f:
                    f.write(code)
                
                # 🔥 НОВОЕ: Засекаем время старта
                start_exec = time.time()
                
                # Запускаем скрипт
                result = subprocess.run(
                    ["python", "temp_task.py"], 
                    capture_output=True, text=True
                )
                
                # 🔥 НОВОЕ: Считаем время выполнения
                execution_duration = round(time.time() - start_exec, 4)
                
                # Читаем вывод (или ошибку)
                output = result.stdout if result.returncode == 0 else result.stderr
                if not output:
                    output = "Code executed silently (no output)."
                
                # 3. Отправляем результат С ВРЕМЕНЕМ выполнения
                requests.post(f"{SERVER_URL}/submit_result", json={
                    "task_id": task_id,
                    "output": output,
                    "execution_time": execution_duration # 🔥 ВОТ ОНО!
                })
                print(f"[+] Result for {task_id} sent. Time taken: {execution_duration}s")
                
                # Убираем за собой мусор
                if os.path.exists("temp_task.py"):
                    os.remove("temp_task.py")
                
        except Exception as e:
            # Если сервер упал, просто ждем
            # print(f"Error: {e}")
            pass
            
        time.sleep(2) # Уменьшил до 2 сек, чтобы быстрее подхватывал

if __name__ == "__main__":
    try:
        start_agent()
    except KeyboardInterrupt:
        print("\n[!] Agent stopped.")