import socket
import json
import threading
import platform
import psutil
import GPUtil
import time
import pygame
import numpy as np
import carla
import math

class CarlaClient:
    def __init__(self, server_ip, server_port):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True

    def connect(self):
        try:
            self.client_socket.connect((self.server_ip, self.server_port))
            print(f"✅ Подключено к серверу {self.server_ip}:{self.server_port}")

            # Автоматическая отправка информации об устройстве
            self.send_device_info()
            threading.Thread(target=self.listen_for_messages, daemon=True).start()

            while self.running:
                print("\nВыберите действие:")
                print("1. Запрос на спавн автомобилей")
                print("2. Получить информацию о транспорте")
                print("3. Отключиться")
                print("5. Выбрать автомобиль для ручного управления")
                choice = input("Введите выбор (1-6): ").strip()

                if choice == "1":
                    num_vehicles = int(input("Введите число автомобилей для спавна: "))
                    self.send_command({"action": "request_spawn", "num_vehicles": num_vehicles})
                elif choice == "2":
                    self.send_command({"action": "get_vehicle_info"})
                elif choice == "3":
                    self.disconnect()
                elif choice == "5":
                    self.manual_control()
                else:
                    print("\n❌ Некорректный ввод, попробуйте снова.")

        except Exception as e:
            print(f"\n❌ Ошибка подключения: {e}")

    def send_command(self, command):
        try:
            self.client_socket.send((json.dumps(command) + "\n").encode())
        except Exception as e:
            print(f"\n❌ Ошибка отправки команды: {e}")

    def listen_for_messages(self):
        buffer = ""
        while self.running:
            try:
                chunk = self.client_socket.recv(1024).decode()
                if not chunk:
                    break
                buffer += chunk
                while "\n" in buffer:
                    json_obj, buffer = buffer.split("\n", 1)
                    command = json.loads(json_obj)
                    self.process_command(command)
            except Exception as e:
                print(f"\n❌ Ошибка при получении данных: {e}")
                break

    def get_device_info(self):
        """Собирает данные о системе: CPU, GPU, RAM и их загрузке"""
        device_info = {
            "OS": platform.system(),
            "OS Version": platform.version(),
            "CPU": platform.processor(),
            "CPU Usage": f"{psutil.cpu_percent()}%",
            "RAM Total": f"{round(psutil.virtual_memory().total / 1024 ** 3, 2)} GB",
            "RAM Used": f"{round(psutil.virtual_memory().used / 1024 ** 3, 2)} GB",
            "RAM Usage": f"{psutil.virtual_memory().percent}%",
            "GPU": [],
        }

        # Получаем информацию о всех доступных GPU
        gpus = GPUtil.getGPUs()
        for gpu in gpus:
            device_info["GPU"].append({
                "Name": gpu.name,
                "Load": f"{gpu.load * 100:.1f}%",
                "Memory Used": f"{gpu.memoryUsed} MB",
                "Memory Total": f"{gpu.memoryTotal} MB"
            })

        return device_info

    def send_device_info(self):
        """Отправляет информацию об устройстве при подключении и затем раз в 5 секунд"""
        def send_loop():
            while self.running:
                device_info = self.get_device_info()
                self.send_command({"action": "send_device_info", "device_info": device_info})
                time.sleep(5)

        # Запускаем фоновый поток для отправки данных каждые 5 секунд
        threading.Thread(target=send_loop, daemon=True).start()

    def process_command(self, command):
        if command.get("action") == "spawn_vehicles":
            num_spawned = command.get("num_vehicles", 0)
            print(f"\n🚗 Сервер сообщил: заспавнено {num_spawned} машин.")
        elif command.get("action") == "vehicle_info":
            vehicles = command.get("vehicles", [])
            print("\n🚙 Ваши машины:")
            for v in vehicles:
                print(f" - ID: {v['id']}, Скорость: {v['speed']} м/с, Позиция: {v['location']}, режим: {v.get('control_mode', 'N/A')}")
        elif command.get("action") == "disconnect":
            print("🔌\nСервер подтвердил отключение.")
            self.disconnect()
        elif command.get("action") == "disconnect_warning":
            print("\n🔌 Сервер отключил Вас принудительно.")
            self.running = False
        else:
            print(f"Получена неизвестная команда: {command}")

    def disconnect(self):
        print("\n🔌 Отключение от сервера...")
        self.running = False
        self.send_command({"action": "disconnect"})
        self.client_socket.close()

    def manual_control(self):
        print("Запуск режима ручного управления с видеопередачей...")

        # Подключаемся к CARLA-серверу
        try:
            carla_client = carla.Client("localhost", 2000)
            carla_client.set_timeout(10.0)
            world = carla_client.get_world()
        except Exception as e:
            print(f"Ошибка подключения к CARLA: {e}")
            return

        # Запрашиваем ID транспортного средства
        vehicle_id_input = input("Введите ID транспортного средства (оставьте пустым для первого найденного): ").strip()
        vehicles = world.get_actors().filter('vehicle.*')

        if not vehicles:
            print("❌ Транспортное средство не найдено! Спавните авто и попробуйте снова.")
            return

        # Ищем транспортное средство
        if vehicle_id_input:
            try:
                vehicle_id = int(vehicle_id_input)
            except ValueError:
                print("❌ Ошибка: ID должно быть числом.")
                return

            vehicle = next((v for v in vehicles if v.id == vehicle_id), None)
            if vehicle is None:
                print(f"❌ Транспортное средство с ID {vehicle_id} не найдено.")
                return
        else:
            vehicle = vehicles[0]

        print(f"✅ Найден транспорт: ID = {vehicle.id}")
        vehicle.set_autopilot(False)
        print("🚗 Автопилот отключён. Включено ручное управление.")

        # Установка камеры (третье лицо)
        blueprint_library = world.get_blueprint_library()
        camera_bp = blueprint_library.find('sensor.camera.rgb')
        camera_transform = carla.Transform(carla.Location(x=-5, z=3))
        camera = world.spawn_actor(camera_bp, camera_transform, attach_to=vehicle)
        print("📷 Камера установлена.")

        # Переменная для видеопотока
        image_surface = None
        lock = threading.Lock()

        def process_img(image):
            array = np.frombuffer(image.raw_data, dtype=np.uint8)
            array = np.reshape(array, (image.height, image.width, 4))
            array = array[:, :, :3][:, :, ::-1]
            return pygame.surfarray.make_surface(array.swapaxes(0, 1))

        def sensor_callback(image):
            nonlocal image_surface
            surface = process_img(image)
            with lock:
                image_surface = surface

        def draw_minimap(display, world, vehicle_location, vehicle_rotation, radius, x, y):
            """ Отрисовывает мини-карту дорог в радиусе 'radius' вокруг машины. """
            pygame.draw.rect(display, (0, 0, 0), (x, y, 200, 200))  # Фон мини-карты
            pygame.draw.rect(display, (200, 200, 200), (x, y, 200, 200), 2)  # Граница

            # Получаем карту дорог
            map = world.get_map()
            waypoints = map.generate_waypoints(2.0)

            for wp in waypoints:
                road_x, road_y = wp.transform.location.x, wp.transform.location.y
                dx, dy = road_x - vehicle_location.x, road_y - vehicle_location.y
                dist = math.sqrt(dx ** 2 + dy ** 2)

                if dist < radius:
                    # Преобразуем координаты в мини-карту
                    map_x = int(x + 100 + (dx / radius) * 100)
                    map_y = int(y + 100 - (dy / radius) * 100)
                    pygame.draw.circle(display, (255, 255, 255), (map_x, map_y), 2)

            # Отрисовываем машину
            pygame.draw.circle(display, (255, 0, 0), (x + 100, y + 100), 5)
            pygame.draw.line(display, (255, 0, 0), (x + 100, y + 100),
                             (x + 100 + 10 * math.cos(math.radians(vehicle_rotation)),
                              y + 100 - 10 * math.sin(math.radians(vehicle_rotation))), 2)

        camera.listen(sensor_callback)

        # Инициализация Pygame
        pygame.init()
        window_width, window_height = 1280, 720
        display = pygame.display.set_mode((window_width, window_height))
        pygame.display.set_caption("CARLA - Ручное управление")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont("Arial", 20)

        try:
            while True:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        raise KeyboardInterrupt

                keys = pygame.key.get_pressed()
                control = carla.VehicleControl()

                # Управление автомобилем (WASD + X)
                if keys[pygame.K_w]:
                    control.throttle = 1.0
                    control.reverse = False
                elif keys[pygame.K_s]:
                    control.throttle = 1.0
                    control.reverse = True
                else:
                    control.throttle = 0.0

                if keys[pygame.K_a]:
                    control.steer = -0.5
                elif keys[pygame.K_d]:
                    control.steer = 0.5
                else:
                    control.steer = 0.0

                control.hand_brake = keys[pygame.K_SPACE]
                vehicle.apply_control(control)

                # Получаем скорость (м/с → км/ч)
                velocity = vehicle.get_velocity()
                speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) * 3.6

                # Отрисовка видеопотока и UI
                display.fill((0, 0, 0))
                with lock:
                    if image_surface:
                        scaled_surface = pygame.transform.scale(image_surface, (window_width, window_height))
                        display.blit(scaled_surface, (0, 0))


                # Получаем местоположение машины
                vehicle_transform = vehicle.get_transform()
                vehicle_location = vehicle_transform.location
                vehicle_rotation = vehicle_transform.rotation.yaw

                # Отрисовка мини-карты
                draw_minimap(display, world, vehicle_location, vehicle_rotation, 100, 20, 200) # радиус, положение по x, положение по y

                # Информационная панель
                info_lines = [
                    f"ID автомобиля: {vehicle.id}",
                    f"Скорость: {speed:.2f} км/ч",
                    f"Газ (W): {control.throttle:.2f}",
                    f"Назад (S): {'Да' if control.reverse else 'Нет'}",
                    f"Руль (A/D): {control.steer:.2f}",
                    f"Ручной тормоз (Пробел): {'Да' if control.hand_brake else 'Нет'}",
                ]
                y_offset = 20
                pygame.draw.rect(display, (30, 30, 30), (10, 10, 280, 190)) #черный прямоугольник (фон) первые две - верхний левый угол вторые 2 размер
                pygame.draw.rect(display, (200, 200, 200), (10, 10, 280, 190), 2) #белая рамка

                for line in info_lines:
                    text_surface = font.render(line, True, (255, 255, 255))
                    display.blit(text_surface, (20, y_offset))
                    y_offset += text_surface.get_height() + 5

                pygame.display.flip()
                clock.tick(30)

        except KeyboardInterrupt:
            print("Остановка режима ручного управления...")

        finally:
            camera.stop()
            camera.destroy()
            pygame.quit()
            vehicle.set_autopilot(True)
            print(f"🚙 Автомобиль {vehicle.id} снова в режиме автопилота.")


if __name__ == "__main__":
    client = CarlaClient("172.23.16.1", 52399)  # Изменяйте в соответствии с IP и портом сервера
    client.connect()
