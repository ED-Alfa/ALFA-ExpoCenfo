import time
import board
import busio
import wifi
import socketpool
import adafruit_requests
from analogio import AnalogIn
from adafruit_httpserver import Server, Request, Response
from i2c_pcf8574_interface import I2CPCF8574Interface
from lcd import LCD, CursorMode

# Set up your Wi-Fi credentials
WIFI_SSID = "EstudiantesWLAN"

# HTTP server URL for storing data
SERVER_URL = "http://10.0.0.200:5000/store_ph"  # Replace with your actual Flask server URL

# Device ID for identification
DEVICE_ID = "device_01"  # Unique identifier for the device

# Initialize LCD
i2c = busio.I2C(board.SCL, board.SDA)
lcd_columns = 16
lcd_rows = 2
lcd = LCD(I2CPCF8574Interface(i2c, 0x27), num_rows=lcd_rows, num_cols=lcd_columns)
lcd.set_cursor_mode(CursorMode.LINE)
lcd.clear()

# Set up the analog pin for the pH sensor
ph_sensor_pin = AnalogIn(board.IO34)  # Adjust the pin number according to your board

# Connect to Wi-Fi
print("Connecting to Wi-Fi...")
wifi.radio.connect(WIFI_SSID)  # No password needed for open networks
print("Connected to Wi-Fi")

# Create a socket pool and HTTP requests object
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool)

# Create an HTTP server
server = Server(pool, "/static")

def read_ph_value(sensor_pin):
    # Convert the analog value to voltage
    voltage = (sensor_pin.value * 3.3) / 65536  # Adjust for your ADC's reference voltage
    # Convert voltage to pH - this requires calibration with known pH solutions
    ph_value = 3.5 * voltage  # Placeholder conversion, calibrate with actual data
    return ph_value

def update_lcd(ph_value):
    # Display pH value on LCD
    lcd.clear()
    lcd.set_cursor_pos(0, 0)
    lcd.print("pH: {:.2f}".format(ph_value))
    lcd.set_cursor_pos(1, 0)
    lcd.print("Updating...    ")

def send_ph_value_to_server(ph_value):
    try:
        # Send a POST request with the pH value and device ID
        response = requests.post(SERVER_URL, json={'ph_value': ph_value, 'device_id': DEVICE_ID})
        print("Server response:", response.text)  # Print server response
        if response.status_code == 200:
            print("pH value sent successfully")
        else:
            print("Failed to send pH value, Status code:", response.status_code)
    except Exception as e:
        print(f"Error sending pH value: {e}")

# Define a route to serve pH value
@server.route("/ph")
def ph(request: Request):
    ph_value = read_ph_value(ph_sensor_pin)
    update_lcd(ph_value)  # Update LCD display
    send_ph_value_to_server(ph_value)  # Send to server
    return Response(request, content_type="text/plain", body="{:.2f}".format(ph_value))

# Define a route to serve the main page
@server.route("/")
def index(request: Request):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script>
            async function updatePH() {
                try {
                    const response = await fetch('/ph');
                    const phValue = await response.text();
                    document.getElementById('phValue').innerText = `Current pH: ${phValue}`;
                } catch (error) {
                    console.error('Error fetching pH value:', error);
                }
            }
            setInterval(updatePH, 1000); // Update every 1000ms (1 second)
        </script>    
        <title>pH Sensor Reading</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f4f4f9;
                color: #333;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                overflow: auto; /* Enable scrolling */
            }
            h1 {
                color: #4CAF50;
            }
            .title {
                position: absolute;
                top: 10px;
                left: 10px;
                font-size: 24px;
                color: #4CAF50;  /* Green color for the project name */
            }
            .container {
                background: #fff;
                border-radius: 20px;
                box-shadow: 0 8px 15px rgba(0, 0, 0, 0.1);
                padding: 20px;
                text-align: center;
                width: 80%;
                max-width: 350px;
                margin-top: 60px; /* Added space for the project title */
                max-height: 400px; /* Set max-height for scrollable content */
                overflow: auto; /* Enable scrolling if content overflows */
            }
            p {
                font-size: 1.5em;
                margin: 0;
            }
            .footer {
                margin-top: 20px;
                font-size: 0.8em;
                color: #666;
            }
        </style>
    </head>
    <body>
        <div class="title">
            Proyecto ALFA
        </div>
        <div class="container">
            <h1>pH Sensor Reading</h1>
            <p id="phValue">Loading...</p>
        </div>
        <div class="footer">
            <p>Updated every second</p>
        </div>
    </body>
    </html>
    """
    return Response(request, content_type="text/html", body=html)

# Start the server
try:
    ipv4 = wifi.radio.ipv4_address
    print(f"Server starting at http://{ipv4}")
    server.start(str(ipv4))
except Exception as e:
    print(f"Failed to start server: {e}")
    while True:
        pass

# Main loop to handle requests and update LCD
while True:
    try:
        server.poll()  # Handle incoming requests
    except Exception as e:
        print("Error handling request:", e)
        continue
