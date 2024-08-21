import sys
import os
import io
import datetime
import threading
import requests
import pandas as pd
import pygame
import pymysql
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QHBoxLayout, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QFileDialog
)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QIcon
import pyqtgraph as pg
from twilio.rest import Client

# Función para establecer la conexión a la base de datos MySQL
def connect_to_database():
    try:
        return pymysql.connect(
            host='mysql-2fe24db4-carlychery7-c0f0.e.aivencloud.com',
            port=10789,
            user='avnadmin',
            password='AVNS_IFdKDCE8B2Gt7CPlkhc',
            db='Alfa',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        print(f"Error al conectar a la base de datos: {e}")
        return None

# Clase principal de la aplicación para monitorizar el pH
class PHMonitorApp(QWidget):
    def _init_(self):
        super()._init_()

        # Configuraciones iniciales
        self.upper_limit = 14.0  # Límite superior de pH
        self.lower_limit = 0.0   # Límite inferior de pH
        self.recipient_whatsapp_number = ""  # Número de WhatsApp para notificaciones
        self.data = pd.DataFrame(columns=["Tiempo", "PH"])  # DataFrame para almacenar datos de pH
        self.db_conn = connect_to_database()  # Conectar a la base de datos
        self.fetch_started = False  # Indicador de si se ha iniciado la recolección de datos
        self.alert_playing = False  # Indicador de si la alerta está sonando
        self.alert_sound_path = os.path.join(os.path.dirname(os.path.abspath(_file_)), "alert.mp3")  # Ruta del archivo de sonido para alertas

        # RFID attributes
        self.authorized_uid = [0x13, 0x28, 0x6a, 0x30]  # Replace with your card's UID
        self.access_granted = False

        # Inicializar el cliente de Twilio y pygame para sonidos
        pygame.mixer.init()
        self.client = Client("ACd51cd186335f4fe2e61a378e7dcb3fd6", "46c2bd852b17db0f85e484c0efafec39")

        # Configurar temporizadores (timers)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_ph_data)  # Conectar el timer a la función que obtiene los datos de pH
        self.rfid_timer = QTimer(self)
        self.rfid_timer.timeout.connect(self.check_rfid_status)  # Conectar el timer al método de verificación de RFID
        self.rfid_timer.start(500)  # Verificar RFID cada medio segundo
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.load_database_records)  # Conectar el timer de actualización a la función que carga registros de la base de datos
        self.refresh_timer.start(5000)  # Actualizar registros cada 5 segundos

        # Inicializar la interfaz de usuario
        self.initUI()

        # Iniciar un hilo en segundo plano para guardar datos en la base de datos
        threading.Thread(target=self.save_data_to_db, daemon=True).start()

    def initUI(self):
        # Configuración de la ventana principal
        self.setWindowTitle("Aplicación de Monitoreo de pH")  # Título de la ventana
        self.setWindowIcon(QIcon("icon.png"))  # Ícono de la ventana
        self.setStyleSheet("""
            QWidget {
                font-family: 'Arial';
                font-size: 14px;
                color: #333;
            }
            QLabel, QPushButton, QLineEdit {
                border: 2px solid #555;
                border-radius: 10px;
                padding: 5px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff, stop:1 #eee);
            }
            QPushButton {
                font-weight: bold;
            }
            QPushButton:hover {
                border: 2px solid #333;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f8f8f8, stop:1 #ddd);
            }
            QTabWidget::pane {
                border-top: 2px solid #C2C7CB;
            }
            QTabBar::tab {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f8f8f8, stop:1 #ddd);
                border: 2px solid #C4C4C3;
                border-bottom-color: #C2C7CB;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 10px;
            }
            QTableWidget {
                gridline-color: #D4D4D4;
            }
        """)

        # Layout principal
        self.layout = QVBoxLayout(self)
        
        # Crear pestañas (tabs) para la interfaz
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        self.setupTabs()

    def setupTabs(self):
        # Configuración de la pestaña principal para monitoreo
        self.main_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Monitoreo")  # Añadir pestaña "Monitoreo"
        self.main_layout = QVBoxLayout(self.main_tab)

        # Etiqueta para mostrar el pH actual
        self.ph_label = QLabel("pH Actual: Recuperando datos...", self)
        self.main_layout.addWidget(self.ph_label)

        # Etiqueta para mostrar el estado de la tarjeta
        self.rfid_status_label = QLabel("", self)
        self.main_layout.addWidget(self.rfid_status_label)

        # Configuración del widget para el gráfico de pH
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground("white")
        self.graphWidget.showGrid(x=True, y=True, alpha=0.3)
        self.main_layout.addWidget(self.graphWidget)
        self.plot = self.graphWidget.plot(pen=pg.mkPen(color="blue", width=2), symbol="o", symbolBrush="orange", symbolSize=5)

        # Configuración de los controles para los límites de pH y el número de WhatsApp
        self.setupControls()

    def setupControls(self):
        # Controles de entrada para límites de pH
        limit_layout = QHBoxLayout()
        self.lower_limit_input = QLineEdit(str(self.lower_limit))
        self.upper_limit_input = QLineEdit(str(self.upper_limit))
        self.set_limits_button = QPushButton("Establecer límites y comenzar")
        self.set_limits_button.clicked.connect(self.update_limits)

        limit_layout.addWidget(QLabel("Límite Inferior:"))
        limit_layout.addWidget(self.lower_limit_input)
        limit_layout.addWidget(QLabel("Límite Superior:"))
        limit_layout.addWidget(self.upper_limit_input)
        limit_layout.addWidget(self.set_limits_button)
        self.main_layout.addLayout(limit_layout)

        # Controles para el número de WhatsApp
        whatsapp_number_layout = QHBoxLayout()
        self.whatsapp_number_input = QLineEdit(self)
        self.whatsapp_number_input.setPlaceholderText("Ingrese su número de teléfono (+CódigoPaísNúmero)")
        whatsapp_number_layout.addWidget(QLabel("Número de WhatsApp:"))
        whatsapp_number_layout.addWidget(self.whatsapp_number_input)
        self.main_layout.addLayout(whatsapp_number_layout)

        # Botón para cerrar la aplicación
        self.quit_button = QPushButton("Salir", self)
        self.quit_button.setFont(QFont("Arial", 12))
        self.quit_button.setStyleSheet("background-color: gray; color: white;")
        self.quit_button.clicked.connect(self.close_application)
        self.main_layout.addWidget(self.quit_button)

        # Pestaña para mostrar los registros de la base de datos
        self.data_tab = QWidget()
        self.tabs.addTab(self.data_tab, "Registros de la Base de Datos")  # Añadir pestaña "Registros de la Base de Datos"
        self.data_layout = QVBoxLayout(self.data_tab)
        self.data_table = QTableWidget()
        self.data_layout.addWidget(self.data_table)
        self.load_database_records()  # Cargar registros desde la base de datos

    def update_limits(self):
        # Función para actualizar los límites de pH y comenzar a recolectar datos
        try:
            self.upper_limit = float(self.upper_limit_input.text())  # Actualizar límite superior
            self.lower_limit = float(self.lower_limit_input.text())  # Actualizar límite inferior

            # Validar el formato del número de WhatsApp
            raw_number = self.whatsapp_number_input.text().strip()
            if not raw_number.startswith("+"):
                QMessageBox.warning(self, "Número de WhatsApp Inválido", "Por favor, ingrese el número en formato internacional, comenzando con '+'.")
                return
            self.recipient_whatsapp_number = "whatsapp:" + raw_number  # Formatear el número para WhatsApp

            # Iniciar el temporizador si no se ha iniciado y acceso RFID está garantizado
            if not self.fetch_started and self.access_granted:
                self.timer.start(1000)  # Ejecutar fetch_ph_data cada segundo
                self.ph_label.setText("pH Actual: Recuperando datos...")
                self.fetch_started = True
            elif not self.access_granted:
                self.rfid_status_label.setText("Tarjeta no autorizada. Por favor, acerque una tarjeta autorizada.")
        except ValueError:
            # Si hay un error, reproducir el sonido de alerta
            threading.Thread(target=self.play_sound, args=(self.alert_sound_path,)).start()

    def check_rfid_status(self):
        # Verificar el estado del acceso RFID
        try:
            uid = self.read_rfid()  # Leer la UID de la tarjeta
            if uid == self.authorized_uid:
                self.access_granted = True
            else:
                self.access_granted = False
                self.rfid_status_label.setText("Tarjeta no autorizada.")
                if self.fetch_started:
                    self.timer.stop()
                    self.ph_label.setText("Acceso denegado. Coloque una tarjeta autorizada.")
                    self.fetch_started = False
        except Exception as e:
            print(f"Error al verificar el estado del RFID: {e}")

    def read_rfid(self):
        # Simulación de la lectura de la UID de una tarjeta RFID
        # Esta función debe conectarse al hardware real para leer la UID de la tarjeta
        # Aquí se simula que se lee una tarjeta y se devuelve su UID
        # Reemplazar esta parte con la lógica real del hardware
        return [0x13, 0x28, 0x6a, 0x30]  # Simular que siempre se lee la tarjeta autorizada

    def fetch_ph_data(self):
        # Función para obtener datos de pH del servidor
        if not self.access_granted:
            self.ph_label.setText("Acceso denegado. Coloque una tarjeta autorizada.")
            return

        response = requests.get("http://192.168.0.94:5000/ph")
        if response.status_code == 200:
            ph = float(response.text.strip())  # Convertir la respuesta a un valor de pH
            current_time = datetime.datetime.now().timestamp()  # Obtener timestamp para el gráfico
            self.data = pd.concat([self.data, pd.DataFrame({"Tiempo": [current_time], "PH": [ph]})], ignore_index=True)
            self.ph_label.setText(f"pH Actual: {ph:.2f}")
            print(f"Datos actualizados con pH: {ph}, Tiempo: {current_time}")  # Imprimir para depuración
            self.update_plot()  # Actualizar el gráfico
            self.check_ph_levels(ph)  # Verificar si el pH está fuera de los límites
            if len(self.data) >= 10:
                self.save_data_to_db()  # Guardar datos en la base de datos si hay suficientes registros

    def update_plot(self):
        # Función para actualizar el gráfico de pH
        if not self.data.empty:
            x = self.data['Tiempo'].values  # Tiempos (timestamps)
            y = self.data['PH'].values  # Valores de pH
            self.plot.setData(x=x, y=y)  # Actualizar los datos del gráfico
            self.graphWidget.autoRange()  # Ajustar el rango automáticamente para ver todos los datos
            print(f"Gráfico actualizado con {len(x)} puntos.")  # Imprimir para depuración

    def check_ph_levels(self, ph):
        # Función para verificar si el pH está dentro de los límites permitidos
        if ph < self.lower_limit or ph > self.upper_limit:
            if not self.alert_playing:
                self.play_sound(self.alert_sound_path)  # Reproducir sonido de alerta
                solution = "más básico" if ph > self.upper_limit else "más ácido"
                alert_message = f"Alerta: ¡El valor de pH está fuera del rango!\n" \
                                f"pH Actual: {ph}\nLa solución es {solution}.\n" \
                                f"Límites establecidos: {self.lower_limit} (inferior), {self.upper_limit} (superior)."
                self.send_whatsapp_message(alert_message)  # Enviar mensaje de alerta por WhatsApp
                self.alert_playing = True
        else:
            self.alert_playing = False

    def send_whatsapp_message(self, message):
        # Función para enviar un mensaje por WhatsApp usando Twilio
        recipient_number = self.whatsapp_number_input.text().strip()
        if not recipient_number.startswith("whatsapp:"):
            recipient_number = "whatsapp:" + recipient_number

        def send_message():
            try:
                message_sent = self.client.messages.create(
                    body=message,
                    from_='whatsapp:+14155238886',  # Twilio Sandbox Number or your Twilio WhatsApp Number
                    to=recipient_number  # The recipient's number entered by the user
                )
                print(f"Mensaje enviado a {recipient_number} con SID {message_sent.sid}")
            except Exception as e:
                print(f"Error al enviar el mensaje de WhatsApp: {e}")

        threading.Thread(target=send_message).start()

    def play_sound(self, sound_path):
        # Función para reproducir un sonido de alerta
        def run_sound():
            try:
                pygame.mixer.init()
                pygame.mixer.music.load(sound_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():  # Esperar a que termine de reproducirse
                    pygame.time.Clock().tick(10)
            except Exception as e:
                print(f"Error al reproducir el sonido: {e}")

        threading.Thread(target=run_sound).start()

    def save_data_to_db(self):
        # Función para guardar los datos de pH en la base de datos
        if len(self.data) >= 1000:
            buffer = io.StringIO()
            self.data.to_csv(buffer, index=False)  # Convertir los datos a formato CSV
            csv_content = buffer.getvalue()
            buffer.close()
            with self.db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO csv_storage (csv_content, recorded_time, filename) VALUES (%s, NOW(), %s)",
                    (csv_content, f"data_snapshot_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
                )
                self.db_conn.commit()
            print("Datos CSV con 1000 mediciones insertados correctamente en la base de datos.")
            self.data = self.data.iloc[0:0]  # Vaciar el DataFrame después de guardar

    def load_database_records(self):
        # Función para cargar los registros desde la base de datos y mostrarlos en la tabla
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT id, recorded_time, filename FROM csv_storage ORDER BY recorded_time DESC")
            records = cursor.fetchall()
        self.data_table.setRowCount(len(records))
        self.data_table.setColumnCount(3)
        self.data_table.setHorizontalHeaderLabels(['Hora registrada', 'Nombre del archivo', 'Descargar'])
        for row_index, row_data in enumerate(records):
            self.data_table.setItem(row_index, 0, QTableWidgetItem(str(row_data['recorded_time'])))
            self.data_table.setItem(row_index, 1, QTableWidgetItem(row_data['filename']))
            download_button = QPushButton("Descargar")
            download_button.clicked.connect(lambda _, id=row_data['id']: self.download_csv(id))
            self.data_table.setCellWidget(row_index, 2, download_button)

    def download_csv(self, record_id):
        # Función para descargar un archivo CSV desde la base de datos
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT csv_content, filename FROM csv_storage WHERE id = %s", (record_id,))
            result = cursor.fetchone()
            if result:
                csv_content = result['csv_content']
                if isinstance(csv_content, bytes):
                    csv_content = csv_content.decode('utf-8')  # Decodificar bytes a cadena
                filename = result['filename']
                file_path, _ = QFileDialog.getSaveFileName(self, "Guardar Archivo CSV", filename, "Archivos CSV (*.csv)")
                if file_path:
                    with open(file_path, 'w') as file:
                        file.write(csv_content)
                    QMessageBox.information(self, "Descarga Exitosa", f"El archivo '{filename}' se ha descargado correctamente.")
                else:
                    QMessageBox.warning(self, "Error de Descarga", "La descarga del archivo fue cancelada o no se seleccionó una ruta.")
            else:
                QMessageBox.warning(self, "Error de Descarga", "No se encontraron datos para el registro seleccionado.")

    def close_application(self):
        # Función para cerrar la aplicación de forma segura
        self.timer.stop()  # Detener el temporizador principal
        self.rfid_timer.stop()  # Detener el temporizador RFID
        self.refresh_timer.stop()  # Detener el temporizador de actualización
        pygame.mixer.music.stop()  # Detener cualquier sonido en reproducción
        if self.db_conn:
            self.db_conn.close()  # Cerrar la conexión a la base de datos
        print("Aplicación cerrada")
        self.close()

# Código para ejecutar la aplicación
if _name_ == "_main_":
    app = QApplication(sys.argv)
    ex = PHMonitorApp()
    ex.show()
    sys.exit(app.exec_())