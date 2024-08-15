import sys
import requests
import pandas as pd
import datetime
import threading
import os
import io
import pygame
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QHBoxLayout, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QFileDialog
)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QIcon
import pyqtgraph as pg
from twilio.rest import Client
import pymysql

def connect_to_database():
    return pymysql.connect(
        host='mysql-2fe24db4-carlychery7-c0f0.e.aivencloud.com',
        port=10789,
        user='avnadmin',
        password='AVNS_IFdKDCE8B2Gt7CPlkhc',
        db='Alfa',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

class PHMonitorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.upper_limit = 14.0
        self.lower_limit = 0.0
        self.recipient_whatsapp_number = ""
        self.data = pd.DataFrame(columns=["Time", "PH"])
        self.db_conn = connect_to_database()
        self.initUI()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_ph_data)
        self.fetch_started = False
        self.alert_playing = False
        self.alert_sound_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert.mp3")
        pygame.mixer.init()
        self.client = Client("AC1514c2e2ba3bf84e6f014722dca6830b", "a22fa24e4310269b36654b5cb171cda0")
        threading.Thread(target=self.save_data_to_db, daemon=True).start()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.load_database_records)
        self.refresh_timer.start(5000)

    def initUI(self):
        self.setWindowTitle("PH Monitor App")
        self.setWindowIcon(QIcon("icon.png"))
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
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #fff, stop:1 #eee);
            }
            QPushButton {
                font-weight: bold;
            }
            QPushButton:hover {
                border: 2px solid #333;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #f8f8f8, stop:1 #ddd);
            }
            QTabWidget::pane {
                border-top: 2px solid #C2C7CB;
            }
            QTabBar::tab {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #f8f8f8, stop:1 #ddd);
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
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        self.setupTabs()

    def setupTabs(self):
        self.main_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Monitor")
        self.main_layout = QVBoxLayout(self.main_tab)
        self.ph_label = QLabel("Current pH: Fetching data...", self)
        self.main_layout.addWidget(self.ph_label)
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground("white")
        self.graphWidget.showGrid(x=True, y=True, alpha=0.3)
        self.main_layout.addWidget(self.graphWidget)
        self.plot = self.graphWidget.plot(pen=pg.mkPen(color="blue", width=2), symbol="o", symbolBrush="orange", symbolSize=5)
        self.setupControls()

    def setupControls(self):
        limit_layout = QHBoxLayout()
        self.upper_limit_input = QLineEdit(str(self.upper_limit))
        self.lower_limit_input = QLineEdit(str(self.lower_limit))
        self.set_limits_button = QPushButton("Set Limits and Start")
        self.set_limits_button.clicked.connect(self.update_limits)
        limit_layout.addWidget(QLabel("Lower Limit:"))
        limit_layout.addWidget(self.lower_limit_input)
        limit_layout.addWidget(QLabel("Upper Limit:"))
        limit_layout.addWidget(self.upper_limit_input)
        limit_layout.addWidget(self.set_limits_button)
        self.main_layout.addLayout(limit_layout)
        whatsapp_number_layout = QHBoxLayout()
        self.whatsapp_number_input = QLineEdit(self)
        self.whatsapp_number_input.setPlaceholderText("Enter your phone number (+CountryCodePhoneNumber)")
        whatsapp_number_layout.addWidget(QLabel("WhatsApp Number:"))
        whatsapp_number_layout.addWidget(self.whatsapp_number_input)
        self.main_layout.addLayout(whatsapp_number_layout)
        self.quit_button = QPushButton("Quit", self)
        self.quit_button.setFont(QFont("Arial", 12))
        self.quit_button.setStyleSheet("background-color: gray; color: white;")
        self.quit_button.clicked.connect(self.close_application)
        self.main_layout.addWidget(self.quit_button)
        self.data_tab = QWidget()
        self.tabs.addTab(self.data_tab, "Database Records")
        self.data_layout = QVBoxLayout(self.data_tab)
        self.data_table = QTableWidget()
        self.data_layout.addWidget(self.data_table)
        self.load_database_records()

    def update_limits(self):
        try:
            self.upper_limit = float(self.upper_limit_input.text())
            self.lower_limit = float(self.lower_limit_input.text())
            raw_number = self.whatsapp_number_input.text().strip()
            if not raw_number.startswith("+"):
                QMessageBox.warning(self, "Invalid WhatsApp Number", "Please enter the phone number in international format, starting with '+'.")
                return
            self.recipient_whatsapp_number = "whatsapp:" + raw_number
            if not self.fetch_started:
                self.timer.start(1000)
                self.ph_label.setText("Current pH: Fetching data...")
                self.fetch_started = True
        except ValueError:
            threading.Thread(target=self.play_sound, args=(self.alert_sound_path,)).start()

    def fetch_ph_data(self):
        response = requests.get("http://10.0.9.29:5000/ph")
        if response.status_code == 200:
            ph = float(response.text.strip())
            current_time = datetime.datetime.now().timestamp()  # Convert to timestamp for plotting
            self.data = pd.concat([self.data, pd.DataFrame({"Time": [current_time], "PH": [ph]})], ignore_index=True)
            self.ph_label.setText(f"Current pH: {ph:.2f}")
            print(f"Data updated with pH: {ph}, Time: {current_time}")  # Debugging print
            self.update_plot()  # Ensure this is called
            self.check_ph_levels(ph)  # Trigger alerts if necessary
            if len(self.data) >= 10:
                self.save_data_to_db()

    def update_plot(self):
        if not self.data.empty:
            x = self.data['Time'].values  # These should be numeric timestamps
            y = self.data['PH'].values
            self.plot.setData(x=x, y=y)  # Update the plot data
            self.graphWidget.autoRange()  # Optional: Auto-range to see all data
            print(f"Plot updated with {len(x)} points.")  # Debugging print

    def check_ph_levels(self, ph):
        if ph < self.lower_limit or ph > self.upper_limit:
            if not self.alert_playing:
                self.play_sound(self.alert_sound_path)
                solution = "more basic" if ph > self.upper_limit else "more acidic"
                alert_message = f"Alert: The pH value is out of range!\nCurrent pH: {ph}\nThe solution is {solution}.\nSet limits: {self.lower_limit} (lower), {self.upper_limit} (upper)."
                self.send_whatsapp_message(alert_message)
                self.alert_playing = True
        else:
            self.alert_playing = False

    def send_whatsapp_message(self, message):
        def send_message():
            try:
                message_sent = self.client.messages.create(
                    body=message,
                    from_='whatsapp:+14155238886',  # This should be the Twilio WhatsApp number
                    to=self.recipient_whatsapp_number  # Ensure this is in 'whatsapp:+1234567890' format
                )
                print(f"Message sent to {self.recipient_whatsapp_number} with SID {message_sent.sid}")
            except Exception as e:
                print(f"Failed to send WhatsApp message due to: {e}")
        
        threading.Thread(target=send_message).start()

    def play_sound(self, sound_path):
        def run_sound():
            try:
                pygame.mixer.init()
                pygame.mixer.music.load(sound_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():  # Wait for music to finish playing
                    pygame.time.Clock().tick(10)
            except Exception as e:
                print(f"Failed to play sound: {e}")

        threading.Thread(target=run_sound).start()

    def save_data_to_db(self):
        if len(self.data) >= 1000:
            buffer = io.StringIO()
            self.data.to_csv(buffer, index=False)
            csv_content = buffer.getvalue()
            buffer.close()
            with self.db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO csv_storage (csv_content, recorded_time, filename) VALUES (%s, NOW(), %s)",
                    (csv_content, f"data_snapshot_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
                )
                self.db_conn.commit()
            print("CSV data with 1000 measurements inserted successfully into the database.")
            self.data = self.data.iloc[0:0]  # Clear the DataFrame after saving

    def load_database_records(self):
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT id, recorded_time, filename FROM csv_storage ORDER BY recorded_time DESC")
            records = cursor.fetchall()
        self.data_table.setRowCount(len(records))
        self.data_table.setColumnCount(3)
        self.data_table.setHorizontalHeaderLabels(['Recorded Time', 'Filename', 'Download'])
        for row_index, row_data in enumerate(records):
            self.data_table.setItem(row_index, 0, QTableWidgetItem(str(row_data['recorded_time'])))
            self.data_table.setItem(row_index, 1, QTableWidgetItem(row_data['filename']))
            download_button = QPushButton("Download")
            download_button.clicked.connect(lambda _, id=row_data['id']: self.download_csv(id))
            self.data_table.setCellWidget(row_index, 2, download_button)

    def download_csv(self, record_id):
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT csv_content, filename FROM csv_storage WHERE id = %s", (record_id,))
            result = cursor.fetchone()
            if result:
                csv_content = result['csv_content']
                if isinstance(csv_content, bytes):
                    csv_content = csv_content.decode('utf-8')  # Decoding bytes to string
                filename = result['filename']
                file_path, _ = QFileDialog.getSaveFileName(self, "Save CSV File", filename, "CSV Files (*.csv)")
                if file_path:
                    with open(file_path, 'w') as file:
                        file.write(csv_content)
                    QMessageBox.information(self, "Download Successful", f"File '{filename}' downloaded successfully.")
                else:
                    QMessageBox.warning(self, "Download Error", "File download was cancelled or no path was selected.")
            else:
                QMessageBox.warning(self, "Download Error", "No data found for the selected record.")

    def on_plot_click(self, event):
        pos = event.scenePos()
        if self.graphWidget.sceneBoundingRect().contains(pos):
            mouse_point = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            x = mouse_point.x()
            y = mouse_point.y()
            # Convert x to timestamp
            timestamp = pd.to_datetime(x, unit='s', origin='unix')
            # Find the index of the closest time point
            nearest_index = (self.data['Time'] - timestamp).abs().idxmin()
            nearest_time = pd.to_datetime(self.data['Time'].iloc[nearest_index], unit='s', origin='unix')
            nearest_ph = self.data['PH'].iloc[nearest_index]
            in_range = "in range" if self.lower_limit <= nearest_ph <= self.upper_limit else "out of range"
            QMessageBox.information(
                self,
                "Point Information",
                f"Time: {nearest_time.strftime('%d/%m/%Y %I:%M %p')}\npH: {nearest_ph:.2f}\nStatus: {in_range}"
            )

    def close_application(self):
        self.timer.stop()
        self.refresh_timer.stop()
        pygame.mixer.music.stop()
        self.db_conn.close()
        print("Application closed")
        self.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = PHMonitorApp()
    ex.show()
    sys.exit(app.exec_())
