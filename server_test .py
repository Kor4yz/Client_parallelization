import socket
import json
import numpy as np
from prettytable import PrettyTable
import carla
import threading
import psutil
import GPUtil
import time
import cv2

class CarlaServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.clients = {}  # {client_id: socket}
        self.client_vehicles = {}  # {client_id: [список машин]}
        self.world = None
        self.monitoring_active = True
        self.client_info = {}

        # Подключение к CARLA
        try:
            self.client = carla.Client("localhost", 2000)
            self.client.set_timeout(10.0)
            self.world = self.client.get_world()
            print(f"✅ CARLA запущена (доступных точек спавна: {len(self.world.get_map().get_spawn_points())})")
        except Exception as e:
            print(f"❌ Ошибка подключения к CARLA: {e}")


    def start(self):
        print(f"🚀 Сервер запущен на {self.host}:{self.port}")
        while True:
            client_socket, client_address = self.server_socket.accept()
            client_id = str(client_address)
            self.clients[client_id] = client_socket
            self.client_vehicles[client_id] = []
            print(f"🔗 Подключен клиент: {client_address} (ID: {client_id})")
            threading.Thread(target=self.handle_client, args=(client_id, client_socket), daemon=True).start()

    def handle_client(self, client_id, client_socket):
        buffer = ""
        try:
            while True:
                chunk = client_socket.recv(1024).decode()
                if not chunk:
                    break
                buffer += chunk
                while "\n" in buffer:
                    json_obj, buffer = buffer.split("\n", 1)
                    command = json.loads(json_obj)
                    self.process_command(client_id, command)
        except ConnectionResetError:
            print(f"⚠️ Клиент {client_id} неожиданно отключился (WinError 10054)")
        except Exception as e:
            print(f"❌ Ошибка клиента {client_id}: {e}")
        finally:
            self.cleanup_client(client_id)

    def process_command(self, client_id, command):
        """Обрабатывает команды от клиента"""
        if command.get("action") != "send_device_info" :
            print(f"📩 Получена команда от {client_id}: {command}")

        if command.get("action") == "request_spawn":
            num_vehicles = command.get("num_vehicles", 10)
            self.spawn_vehicles(client_id, num_vehicles)

        elif command.get("action") == "get_vehicle_info":
            self.send_vehicle_info(client_id)

        elif command.get("action") == "disconnect":
            self.cleanup_client(client_id)
            self.send_message(client_id, {"action": "disconnect"})

        elif command.get("action") == "send_device_info":
            device_info = command.get("device_info", {})
            if device_info:
                self.client_info[client_id] = device_info

        else:
            print(f"Неизвестная команда от {client_id}: {command}")

    def show_clients_table(self):
        table = PrettyTable()

        # Заголовки таблицы (динамически подстраиваемся под все возможные поля)
        all_keys = set()
        for info in self.client_info.values():
            all_keys.update(info.keys())

        # Фильтруем и сортируем ключи для удобства
        main_keys = ["OS", "OS Version", "CPU", "CPU Usage", "RAM Total", "RAM Used", "RAM Usage"]
        gpu_keys = ["GPU"]
        other_keys = sorted(all_keys - set(main_keys) - set(gpu_keys))  # Остальные ключи

        table.field_names = ["Client ID"] + main_keys + other_keys + ["GPU Info"]

        for client_id, info in self.client_info.items():
            row = [client_id]  # Начинаем с ID клиента

            # Добавляем основную информацию
            for key in main_keys + other_keys:
                row.append(info.get(key, "N/A"))

            # Обрабатываем GPU (если несколько, соединяем их)
            gpu_data = "N/A"
            if info.get("GPU"):
                gpu_data = "\n".join([
                    f"{gpu['Name']} (Load: {gpu['Load']}, VRAM: {gpu['Memory Used']}/{gpu['Memory Total']})"
                    for gpu in info["GPU"]
                ])

            row.append(gpu_data)
            table.add_row(row)

        print("\n" + table.get_string() + "\n")

    def spawn_vehicles(self, client_id, num):
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.filter("vehicle.*")[0]
        spawn_points = self.world.get_map().get_spawn_points()
        spawned_vehicles = []

        for i in range(min(num, len(spawn_points))):
            vehicle = self.world.try_spawn_actor(vehicle_bp, spawn_points[i])
            if vehicle:
                vehicle.set_autopilot(True)
                spawned_vehicles.append({"vehicle": vehicle, "control_mode": "autopilot"})
                self.client_vehicles[client_id].append({"vehicle": vehicle, "control_mode": "autopilot"})
                print(f"Автомобиль {vehicle.id} заспавнен для клиента {client_id} (автопилот)")

        self.send_message(client_id, {"action": "spawn_vehicles", "num_vehicles": len(spawned_vehicles)})

    def send_vehicle_info(self, client_id):
        """Отправка информации о транспортных средствах клиента"""
        vehicles_info = []
        if client_id in self.client_vehicles:
            for item in self.client_vehicles[client_id]:
                vehicle = item["vehicle"]
                if vehicle.is_alive:
                    transform = vehicle.get_transform()
                    velocity = vehicle.get_velocity()
                    vehicles_info.append({
                        "id": vehicle.id,
                        "speed": round((velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) ** 0.5, 2),
                        "location": {"x": round(transform.location.x, 2), "y": round(transform.location.y, 2)},
                        "control_mode": item["control_mode"]
                    })
            self.send_message(client_id, {"action": "vehicle_info", "vehicles": vehicles_info})
        else:
            self.send_message(client_id, {"action": "vehicle_info", "vehicles": []})
    def cleanup_client(self, client_id):
        """Очистка информации о клиенте и уничтожение его транспортных средств с задержкой 5 секунд."""
        if client_id in self.clients:
            self.send_message(client_id, {
                "action": "disconnect_warning",
                "message": "Время ожидания истекло. Через 5 секунд произойдет отключение."
            })
            print(f"Отключение клиента {client_id} через 5 секунд...")
            time.sleep(5)
            if client_id in self.client_vehicles:
                for item in self.client_vehicles[client_id]:
                    vehicle = item["vehicle"]
                    try:
                        if vehicle and vehicle.is_alive:
                            print(f"Уничтожение автомобиля {vehicle.id} (клиент {client_id})...")
                            vehicle.destroy()
                            print(f"Автомобиль {vehicle.id} уничтожен.")
                        else:
                            print(f"Автомобиль {vehicle.id} уже не активен (клиент {client_id}).")
                    except Exception as e:
                        print(f"Ошибка уничтожения автомобиля {vehicle.id}: {e}")
                del self.client_vehicles[client_id]
            if client_id in self.clients:
                self.clients[client_id].close()
                del self.clients[client_id]
            print(f"Клиент {client_id} отключен.")

    def send_message(self, client_id, message):
        """Отправка JSON-сообщения клиенту"""
        try:
            if client_id in self.clients:
                self.clients[client_id].send((json.dumps(message) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            print(f"Ошибка отправки сообщения клиенту {client_id}: соединение потеряно.")

    def server_menu(self):
        """Меню управления сервером"""
        while True:
            print("\n📌 Меню управления сервером:")
            print("1. Показать список клиентов")
            print("2. Показать список транспортных средств")
            print("3. Удалить автомобиль по ID")
            print("4. Отключить клиента по ID")
            print("5. Начать мониторинг ресурсов")
            print("6. Остановить мониторинг ресурсов")
            print("7. Отключить все (убить все транспортные средства)")
            print("8. Показать информацию о клиентах")
            print("9. Выход")

            choice = input("Выберите действие: ")
            if choice == "1":
                self.show_clients()
            elif choice == "2":
                self.show_vehicles()
            elif choice == "3":
                vehicle_id = int(input("Введите ID машины для удаления: "))
                self.remove_vehicle_by_id(vehicle_id)
            elif choice == "4":
                client_id = input("Введите ID клиента для отключения: ")
                self.cleanup_client(client_id)
            elif choice == "5":
                if not hasattr(self, "monitor_thread") or not self.monitor_thread.is_alive():
                    self.monitoring_active = True
                    self.monitor_thread = threading.Thread(target=self.monitor_resources_loop, daemon=True)
                    self.monitor_thread.start()
                    print("✅ Мониторинг ресурсов запущен в отдельном потоке")
                else:
                    print("⚠️ Мониторинг уже запущен")
            elif choice == "6":
                if hasattr(self, "monitor_thread") and self.monitor_thread.is_alive():
                    self.stop_monitoring()
                    print("🛑 Мониторинг остановлен")
                else:
                    print("⚠️ Мониторинг не был запущен")
            elif choice == "7":
                self.cleanup_all()
            elif choice == "8":
                self.show_clients_table()
            elif choice == "9":
                break

    def show_clients(self):
        """Выводит список клиентов"""
        print("\n🔗 Клиенты на сервере:")
        for client_id in self.clients.keys():
            print(f"🔹 {client_id}")

    def show_vehicles(self):
        """Вывод списка транспортных средств"""
        print("\nТранспортные средства:")
        for client_id, vehicles in self.client_vehicles.items():
            for item in vehicles:
                vehicle = item["vehicle"]
                mode = item["control_mode"]
                print(f" - ID: {vehicle.id}, Клиент: {client_id}, Режим: {mode}")

    def remove_vehicle_by_id(self, vehicle_id):
        """Удаление автомобиля по его ID"""
        for client_id, vehicles in self.client_vehicles.items():
            for item in vehicles:
                if item["vehicle"].id == vehicle_id:
                    try:
                        item["vehicle"].destroy()
                        vehicles.remove(item)
                        print(f"Автомобиль {vehicle_id} удален.")
                        return
                    except Exception as e:
                        print(f"Ошибка удаления автомобиля {vehicle_id}: {e}")
                        return
        print("Автомобиль не найден.")

    def monitor_resources_loop(self):
        """Непрерывный мониторинг ресурсов с возможностью остановки"""
        last_net = psutil.net_io_counters()
        while self.monitoring_active:
            cpu_usage = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            net = psutil.net_io_counters()

            net_in = (net.bytes_recv - last_net.bytes_recv) / 1024 / 1024  # МБ
            net_out = (net.bytes_sent - last_net.bytes_sent) / 1024 / 1024  # МБ
            last_net = net

            gpu_info = "N/A"
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_info = f"GPU: {gpus[0].load * 100:.1f}% (VRAM: {gpus[0].memoryUsed}MB/{gpus[0].memoryTotal}MB)"

            print(f"📊 CPU: {cpu_usage:.1f}%, RAM: {ram.used / 1024 ** 3:.2f}/{ram.total / 1024 ** 3:.2f}GB "
                  f"Net ⬇ {net_in:.2f}MB ⬆ {net_out:.2f}MB {gpu_info}")

            time.sleep(5)  # Интервал обновления

    def stop_monitoring(self):
        """Останавливает поток мониторинга ресурсов"""
        self.monitoring_active = False

    def cleanup_all(self):
        """Удаляет всех клиентов и машины на сервере"""
        print("\n🧹 Очистка CARLA от всех машин и клиентов...")

        # Удаляем все машины
        all_vehicles = self.world.get_actors().filter("vehicle.*")
        for vehicle in all_vehicles:
            try:
                vehicle.destroy()
                print(f"✅ Машина {vehicle.id} удалена")
            except Exception as e:
                print(f"❌ Ошибка при удалении машины {vehicle.id}: {e}")

        # Отключаем всех клиентов
        for client_id in list(self.clients.keys()):  # Создаём копию списка ключей, чтобы изменять словарь в процессе
            self.cleanup_client(client_id)

        print("🛑 Все машины и клиенты успешно удалены!")

    def show_client_info(self, client_id=None):
        """Выводит информацию о клиентах"""
        if not self.client_info:
            print("❌ Нет данных об устройствах клиентов!")
            return

        if client_id:
            if client_id in self.client_info:
                print(f"\n💻 Информация о клиенте {client_id}:")
                for key, value in self.client_info[client_id].items():
                    print(f"  {key}: {value}")
            else:
                print(f"❌ Клиент {client_id} не найден!")
        else:
            print("\n💻 Информация обо всех клиентах:")
            for cid, info in self.client_info.items():
                print(f"\n🔹 Клиент {cid}:")
                for key, value in info.items():
                    print(f"  {key}: {value}")
                print("-" * 30)


if __name__ == "__main__":
    server = CarlaServer("0.0.0.0", 52399)
    # Запускаем сервер в отдельном потоке
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()

    # Запускаем меню управления сервером
    server.server_menu()
