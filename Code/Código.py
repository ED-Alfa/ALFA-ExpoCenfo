import time
import board
import busio
import wifi
import socketpool
from analogio import AnalogIn
from adafruit_httpserver import Server, Request, Response, FileResponse
from i2c_pcf8574_interface import I2CPCF8574Interface
from lcd import LCD, CursorMode
import mfrc522

# Configura tus credenciales de Wi-Fi aqui
WIFI_SSID = "Apartamento Piso 1"
WIFI_PASSWORD = "phillips49"

# Aqui se inicializa la pantalla LCD
i2c = busio.I2C(board.SCL, board.SDA)
lcd_columns = 16
lcd_rows = 2
lcd = LCD(I2CPCF8574Interface(i2c, 0x27), num_rows=lcd_rows, num_cols=lcd_columns)
lcd.set_cursor_mode(CursorMode.LINE)
lcd.clear()

# Configura el pin analógico para el sensor de pH
ph_sensor_pin = AnalogIn(board.IO34)


# Conecta al Wi-Fi
print("Conectando a Wi-Fi...")
try:
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Conectado a Wi-Fi")
except ConnectionError as e:
    print(f"Error al conectar a Wi-Fi: {e}")
    while True:
        pass

# Crea un pool de sockets
pool = socketpool.SocketPool(wifi.radio)

# Crea un servidor HTTP
server = Server(pool, "/static")

# Inicializa el lector RFID
lector = mfrc522.MFRC522(
    board.SCK,  # Pin SCK
    board.MOSI,  # Pin MOSI
    board.MISO,  # Pin MISO
    board.IO4,   # Pin RST
    board.IO5,   # Pin SDA
)
lector.set_antenna_gain(0x07 << 4)

# UID autorizado
authorized_uid = [0x13, 0x28, 0x6a, 0x30]

# Bandera para controlar la obtención de datos de pH
fetch_ph_data = False

# Datos de calibración cargados desde tu archivo
calibration_data = [
    (2.72, 7.0),
    (3.16, 4.0),
    (2.23, 10.0)
]

# Función para leer el voltaje bruto del sensor de pH
def read_voltage(sensor_pin):
    return (sensor_pin.value * 3.3) / 65536  # Ajusta para el voltaje de referencia de tu ADC

# Función para calcular el pH a partir del voltaje usando interpolación lineal
def calculate_ph(voltage):
    # Ordena los datos de calibración por voltaje para una interpolación adecuada
    calibration_data.sort()
    
    # Si el voltaje coincide exactamente con uno de los puntos de calibración
    for v, p in calibration_data:
        if voltage == v:
            return p
    
    # Interpolación lineal entre puntos de calibración
    for i in range(len(calibration_data) - 1):
        v1, p1 = calibration_data[i]
        v2, p2 = calibration_data[i + 1]
        
        if v1 <= voltage <= v2:
            # Calcula la pendiente
            slope = (p2 - p1) / (v2 - v1)
            # Calcula el valor de pH
            ph_value = p1 + slope * (voltage - v1)
            return ph_value
    
    # Si el voltaje está fuera del rango de calibración, devuelve None o un valor por defecto
    return None  # o devuelve un valor por defecto como 7.0

# Función para actualizar la pantalla LCD con el valor de pH
def update_lcd(ph_value):
    # Muestra el valor de pH en la pantalla LCD
    lcd.clear()
    lcd.set_cursor_pos(0, 0)
    lcd.print("pH: {:.2f}".format(ph_value))
    lcd.set_cursor_pos(1, 0)
    lcd.print("Actualizando...")

# Define una ruta para servir el valor de pH
@server.route("/ph")
def ph(request: Request):
    if fetch_ph_data:
        voltage = read_voltage(ph_sensor_pin)
        ph_value = calculate_ph(voltage)
        update_lcd(ph_value)  # Actualiza la pantalla LCD
        return Response(request, content_type="text/plain", body="{:.2f}".format(ph_value))
    else:
        return Response(request, content_type="text/plain", body="RFID no autorizado")

# Define una ruta para la página principal
@server.route("/")
def index(request: Request):
    html = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Lectura de Sensor de pH - Alfaponics</title>
        <style>
            body {
                font-family: 'Arial', sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f4f4f9;
                color: #333;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
            }
            h1 {
                font-size: 2.5em;
                margin: 0;
                color: #4CAF50;
                text-align: center;
            }
            .container {
                background: rgba(255, 255, 255, 0.9);
                border-radius: 15px;
                padding: 20px;
                text-align: center;
                width: 80%;
                max-width: 300px;
                box-shadow: 0 8px 15px rgba(0, 0, 0, 0.1);
            }
            p {
                font-size: 1.5em;
                margin: 10px 0;
                color: #4CAF50;
            }
            .footer {
                margin-top: 20px;
                font-size: 0.9em;
                color: #777;
                text-align: center;
            }
        </style>
        <script>
            async function updatePH() {{
                try {{
                    const response = await fetch('/ph');
                    const phValue = await response.text();
                    document.getElementById('phValue').innerText = "pH Actual: " + phValue;
                }} catch (error) {{
                    console.error('Error al obtener el valor del pH:', error);
                }}
            }}
            setInterval(updatePH, 1000); // Actualiza cada 1000ms (1 segundo)
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Lectura de Sensor de pH</h1>
            <p id="phValue">Cargando...</p>
        </div>
        <div class="footer">
            <p>Proyecto Alfaponics - Tecnología para la autoregulación del pH en sistemas hidropónicos.</p>
            <p>Actualizado cada segundo</p>
        </div>
    </body>
    </html>
    """
    return Response(request, content_type="text/html", body=html)

# Función para verificar la tarjeta RFID
def check_rfid():
    global fetch_ph_data
    print("Buscando tarjeta RFID...")
    estado, tipo_tarjeta = lector.request(lector.REQIDL)
    if estado == lector.OK:
        print("¡Tarjeta detectada!")
        estado, uid = lector.anticoll()
        if estado == lector.OK:
            print("Nueva tarjeta detectada")
            print("  - Tipo de tarjeta: 0x%02x" % tipo_tarjeta)
            print("  - UID: 0x%02x%02x%02x%02x" % (uid[0], uid[1], uid[2], uid[3]))
            print('')

            # Verifica si el UID coincide
            if uid[:4] == authorized_uid:
                fetch_ph_data = not fetch_ph_data  # Alterna el estado
                if fetch_ph_data:
                    print("Autorización concedida. Comenzando la recopilación de datos.")
                else:
                    print("Autorización retirada. Deteniendo la recopilación de datos.")
            else:
                print("Tarjeta no autorizada")
        else:
            print("No se pudo leer el UID de la tarjeta.")
    else:
        print("No se detectó ninguna tarjeta.")

# Inicia el servidor
try:
    ipv4 = wifi.radio.ipv4_address
    print(f"Servidor iniciando en http://{ipv4}")
    server.start(str(ipv4))
except Exception as e:
    print(f"Error al iniciar el servidor: {e}")
    while True:
        pass

# Bucle principal para manejar solicitudes, lectura de RFID y actualización de la pantalla LCD
while True:
    try:
        check_rfid()  # Verifica la presencia de la tarjeta RFID
        server.poll()  # Maneja las solicitudes entrantes
    except Exception as e:
        print("Error manejando la solicitud:", e)
        continue
    time.sleep(1)  # Espera 1 segundo antes de volver a verificar