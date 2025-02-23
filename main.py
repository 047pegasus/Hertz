import httpx
import json
from datetime import datetime
from pathlib import Path
from textual import on, work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Header, Footer, DataTable, Static, Input, Button, Label
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual_plotext import PlotextPlot

# Constants
DEFAULT_HOST = "localhost"
DEFAULT_INTERVAL = 10  # seconds
GRAPH_INTERVAL = 5  # seconds
CONFIG_FILE = "hertz_config.json"

# Modal for adding a new service
class AddServiceModal(ModalScreen):
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add New Service"),
            Input(placeholder="Service Name", id="name-input"),
            Input(value=DEFAULT_HOST, placeholder="Host", id="host-input"),
            Input(placeholder="Port", id="port-input"),
            Input(placeholder="Path (optional)", id="path-input"),
            Input(placeholder="Check Interval (seconds)", id="interval-input"),
            Horizontal(
                Button("Cancel", variant="error", id="cancel"),
                Button("Add", variant="success", id="add"),
            ),
            id="add-service-modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            name = self.query_one("#name-input", Input).value.strip()
            host = self.query_one("#host-input", Input).value.strip()
            port = self.query_one("#port-input", Input).value.strip()
            path = self.query_one("#path-input", Input).value.strip() or "/"
            interval = self.query_one("#interval-input", Input).value.strip() or str(DEFAULT_INTERVAL)
            
            if name and host and port and interval:
                self.dismiss({
                    "name": name,
                    "url": f"http://{host}:{port}",
                    "path": path,
                    "check_interval": int(interval),
                    "history": []  # Initialize history for new services
                })
            else:
                self.dismiss(None)
        elif event.button.id == "cancel":
            self.dismiss(None)

class ErrorScreen(ModalScreen):
    def __init__(self, message: str):
        self.message = message
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Error"),
            Label(self.message),
            Button("OK", id="ok"),
            id="error-modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss()
    
    def key_q(self):
        """Handle 'q' key press to quit the application."""
        self.action_quit()

# Main Hertz application
class HertzDashboard(App):
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 2fr 3fr;
    }
    
    #services-container {
        height: 100%;
        border: solid $accent;
        margin: 1;
    }
    
    #graph-container {
        height: 100%;
        border: solid $accent;
        margin: 1;
    }
    
    #services-table {
        width: 100%;
        height: 100%;  /* Ensure the table takes full height */
    }
    
    #status-bar {
        height: 15%;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }
    
    #add-service-modal {
        padding: 2;
        width: 50;
        height: auto;
        background: $surface;
    }
    """

    # Reactive state for monitored applications
    services = reactive([])
    current_service = reactive(None)
    status = reactive("Ready")
    
    row_keys = {}
    column_keys = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(DataTable(id="services-table"), id="services-container")
        yield Vertical(
            PlotextPlot(id="uptime-graph"),  # Use PlotextPlot
            id="graph-container"
        )
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        # Load services from config file if it exists
        self.load_services_from_config()
        
        # Initialize the dashboard
        self.set_interval(DEFAULT_INTERVAL, self.check_services)
        self.set_interval(GRAPH_INTERVAL, self.update_graph)
        self.update_status("Press 'a' to add a service | 'q' to quit")
        self.init_graph()

    def load_services_from_config(self):
        """Load services from hertz_config.json if it exists."""
        config_file = Path(CONFIG_FILE)
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    services = json.load(f)
                    self.services = services
                    table = self.query_one("#services-table", DataTable)
                    column_keys = table.add_columns("Name", "URL", "Path", "Status", "Last Check")
                    self.column_keys = {
                        "Name": column_keys[0],
                        "URL": column_keys[1],
                        "Path": column_keys[2],
                        "Status": column_keys[3],
                        "Last Check": column_keys[4],
                    }
                    for service in services:
                        row_key = table.add_row(
                            service["name"],
                            service["url"],
                            service["path"],
                            "PENDING",
                            "N/A",
                        )
                        self.row_keys[service["name"]] = row_key
            except Exception as e:
                self.show_error(f"Failed to load config: {str(e)}")

    def save_services_to_config(self):
        """Save services to hertz_config.json."""
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.services, f, indent=4)
        except Exception as e:
            self.show_error(f"Failed to save config: {str(e)}")

    def init_graph(self):
        """Initialize the Plotext graph."""
        graph = self.query_one("#uptime-graph", PlotextPlot)
        plt = graph.plt
        plt.date_form("H:M:S")
        plt.title("Uptime Monitoring")
        plt.xlabel("Time")
        plt.ylabel("Latency (s)")
        plt.grid(True)

    @work
    async def check_services(self) -> None:
        """Check the uptime of all monitored services."""
        for service in self.services:
            url = f"{service['url']}{service['path']}"
            try:
                async with httpx.AsyncClient() as client:
                    start = datetime.now()
                    response = await client.get(url, timeout=5)
                    latency = (datetime.now() - start).total_seconds()
                    status = "UP" if response.status_code == 200 else "DOWN"
            except Exception as e:
                status = "ERROR"
                latency = 0
                self.show_error(str(e))

            if "history" not in service:
                service["history"] = []  # Ensure history is initialized
            service["history"].append({
                "timestamp": datetime.now(),
                "status": status,
                "latency": latency
            })
            self.update_service_row(service)

    def update_service_row(self, service):
        """Update the service row in the DataTable."""
        try:
            table = self.query_one("#services-table", DataTable)
            history = service.get("history", [])
            last_status = history[-1]["status"] if history else "UNKNOWN"
            last_check = history[-1]["timestamp"].strftime("%H:%M:%S") if history else "N/A"
            # Get the row key for the service
            row_key = self.row_keys.get(service["name"])
            if row_key is not None:
                table.update_cell(row_key, self.column_keys["Status"], last_status)
                table.update_cell(row_key, self.column_keys["Last Check"], last_check)
        except Exception as e:
            self.show_error(f"Failed to update service row: {str(e)}")

    async def update_graph(self):
        """Update the Plotext graph for the selected service."""
        if self.current_service:
            graph = self.query_one("#uptime-graph", PlotextPlot)
            plt = graph.plt
            history = self.current_service.get("history", [])
            timestamps = [entry["timestamp"].strftime("%H:%M:%S") for entry in history[-30:]]
            latencies = [entry["latency"] for entry in history[-30:]]
            
            plt.clear_data()
            plt.plot(timestamps, latencies, marker="dot")
            plt.title("Uptime Monitoring")
            plt.xlabel("Time")
            plt.ylabel("Latency (s)")
            plt.grid(True)
            graph.refresh()

    def update_status(self, message: str):
        """Update the status bar with a message."""
        self.query_one("#status-bar", Static).update(message)

    def show_error(self, message: str):
        """Display an error message in a modal."""
        self.app.push_screen(ErrorScreen(message))

    @on(DataTable.RowSelected)
    async def show_service_details(self, event: DataTable.RowSelected):
        """Handle row selection to show service details."""
        if event.row_index is not None and event.row_index < len(self.services):
            self.current_service = self.services[event.row_index]
            await self.update_graph()

    def action_add_service(self):
        """Open the modal to add a new service."""
        def add_service_callback(result):
            if result:
                self.services.append(result)
                table = self.query_one("#services-table", DataTable)
                row_key = table.add_row(
                    result["name"],
                    result["url"],
                    result["path"],
                    "PENDING",
                    "N/A"
                )
                self.row_keys[result["name"]] = row_key
                self.save_services_to_config()
                self.update_status(f"Added new service: {result['name']}")
                table.refresh()

        self.push_screen(AddServiceModal(add_service_callback))

    def action_quit(self):
        """Quit the application."""
        self.exit()
        
    def key_a(self):
        """Handle 'a' key press to add a service."""
        self.action_add_service()

    def key_q(self):
        """Handle 'q' key press to quit the application."""
        self.action_quit()

# Run the application
if __name__ == "__main__":
    HertzDashboard().run()