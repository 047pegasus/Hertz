from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Button, Input, DataTable, Label
from textual.reactive import reactive
from textual.screen import Screen
from textual.binding import Binding
from rich.text import Text
from textual.message import Message
import asyncio
import aiohttp
from datetime import datetime
import json
import os

class ServiceConfig:
    def __init__(self, name: str, url: str, path: str = "/", check_interval: int = 30):
        self.name = name
        self.url = url
        self.path = path
        self.check_interval = check_interval
        self.status = "Unknown"
        self.last_check = None
        self.response_time = None

class AddServiceModal(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Close")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Add New Service", classes="modal-title"),
            Input(placeholder="Service Name", id="service_name"),
            Input(placeholder="Host:Port (e.g., localhost:8080)", id="host_port"),
            Input(placeholder="Path (default: /)", id="path", value="/"),
            Input(placeholder="Check Interval (seconds)", id="interval", value="30"),
            Horizontal(
                Button("Add", variant="primary", id="add"),
                Button("Cancel", variant="error", id="cancel"),
                classes="modal-buttons"
            ),
            classes="modal-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            name = self.query_one("#service_name").value
            host_port = self.query_one("#host_port").value
            path = self.query_one("#path").value
            interval = self.query_one("#interval").value

            if not all([name, host_port]):
                self.app.push_screen(ErrorModal("All fields are required!"))
                return

            try:
                interval = int(interval)
            except ValueError:
                self.app.push_screen(ErrorModal("Interval must be a number!"))
                return

            # Construct the full URL
            if not host_port.startswith(("http://", "https://")):
                host_port = f"http://{host_port}"

            service = ServiceConfig(name, host_port, path, interval)
            self.app.get_screen(MainScreen).add_service(service)
            self.app.pop_screen()
        else:
            self.app.pop_screen()

class ErrorModal(Screen):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Error", classes="modal-title error"),
            Static(self.message),
            Button("OK", variant="primary", id="ok"),
            classes="modal-container"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

class ServiceStatus(Container):
    def __init__(self, service: ServiceConfig):
        super().__init__()
        self.service = service
        self._status = Label("Status: Unknown", id="status-label")
        self._last_check = Label("Last Check: Never", id="last-check-label")
        self._response_time = Label("Response Time: N/A", id="response-time-label")

    def compose(self) -> ComposeResult:
        yield Label(self.service.name, classes="service-name")
        yield Static(self.service.url + self.service.path, classes="service-url")
        yield self._status
        yield self._last_check
        yield self._response_time

    def update_status(self, status: str) -> None:
        self._status.update(f"Status: {status}")

    def update_last_check(self, last_check: str) -> None:
        self._last_check.update(f"Last Check: {last_check}")

    def update_response_time(self, response_time: str) -> None:
        self._response_time.update(f"Response Time: {response_time}")

class MainScreen(Screen):
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("a", "add_service", "Add Service", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.services: list[ServiceConfig] = []
        self.service_widgets: dict[str, ServiceStatus] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(id="dashboard")
        yield Footer()

    def on_mount(self) -> None:
        self.load_config()

    def action_add_service(self) -> None:
        self.app.push_screen(AddServiceModal())

    def add_service(self, service: ServiceConfig) -> None:
        self.services.append(service)
        self.save_config()
        service_widget = ServiceStatus(service)
        self.service_widgets[service.name] = service_widget
        self.query_one("#dashboard").mount(service_widget)
        asyncio.create_task(self.monitor_service(service_widget))

    async def monitor_service(self, widget: ServiceStatus) -> None:
        service = widget.service
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    start_time = datetime.now()
                    url = f"{service.url.rstrip('/')}{service.path}"
                    
                    async with session.get(url) as response:
                        end_time = datetime.now()
                        response_time = (end_time - start_time).total_seconds() * 1000
                        
                        if response.status == 200:
                            widget.update_status("UP")
                            widget.update_response_time(f"{response_time:.2f}ms")
                        else:
                            widget.update_status(f"DOWN ({response.status})")
                            widget.update_response_time("N/A")
                            
                except Exception as e:
                    widget.update_status(f"ERROR: {str(e)}")
                    widget.update_response_time("N/A")
                
                widget.update_last_check(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                await asyncio.sleep(service.check_interval)

    def save_config(self) -> None:
        config = [{
            "name": service.name,
            "url": service.url,
            "path": service.path,
            "check_interval": service.check_interval
        } for service in self.services]
        
        with open("hertz_config.json", "w") as f:
            json.dump(config, f)

    def load_config(self) -> None:
        if not os.path.exists("hertz_config.json"):
            return
            
        try:
            with open("hertz_config.json", "r") as f:
                config = json.load(f)
                
            for service_config in config:
                service = ServiceConfig(
                    service_config["name"],
                    service_config["url"],
                    service_config["path"],
                    service_config["check_interval"]
                )
                self.add_service(service)
        except Exception as e:
            self.app.push_screen(ErrorModal(f"Error loading config: {str(e)}"))

class HertzApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    .modal-container {
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }

    .modal-title {
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    .modal-title.error {
        color: red;
    }

    .modal-buttons {
        width: 100%;
        height: 3;
        align: center middle;
    }

    #dashboard {
        width: 100%;
        height: 100%;
        background: $surface;
        padding: 1;
    }

    ServiceStatus {
        width: 100%;
        height: auto;
        border: solid $primary;
        margin: 1 0;
        padding: 1 2;
        background: $panel;
    }

    .service-name {
        text-style: bold;
        color: $primary;
    }

    .service-url {
        color: $text-muted;
    }

    #status-label, #last-check-label, #response-time-label {
        margin-top: 1;
    }

    Input {
        margin: 1 0;
    }

    Button {
        margin: 1 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield MainScreen()

    def on_mount(self) -> None:
        self.install_screen(MainScreen(), name="main")
        self.push_screen("main")

if __name__ == "__main__":
    app = HertzApp()
    app.run()