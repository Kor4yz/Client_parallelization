# 🚗 CARLA Parallel Clients

Параллельное управление множеством клиентов в симуляторе CARLA для масштабируемых экспериментов.

![Architecture Diagram](./docs/architecture.png)

## 📹 Демонстрация

<!-- Вариант 1: GIF-анимация -->
![Demo GIF](./docs/demo.gif)

<!-- Вариант 2: Встроенное YouTube‑видео -->
[![YouTube Demo](carla.jpg)]([https://www.youtube.com/watch?v=ВАШ_ID](https://youtu.be/Rylt8FpgNLU))

## 🔥 Особенности

- **Параллельное** управление N клиентами через Python API
- Автоматическое **распределение** заданий по потокам/процессам
- **Синхронизация** и сбор телеметрии из каждого клиента
- Поддержка **Docker** для воспроизводимости

## 📦 Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/username/carla-parallel-clients.git
   cd carla-parallel-clients
