import json
import os
import csv
import time

import paho.mqtt.client as mqtt

class MQTTStreamer:
    """Manages the MQTT connection and handles data broadcasting payloads."""

    def __init__(self, broker: str, port: int, topic: str, username: str, password: str, debug: bool = False):
        self.broker = broker
        self.port = port
        self.topic = topic
        # self.username = username
        # self.password = password
        
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self.client.username_pw_set(username, password)
        self.debug = debug

    def connect(self):
        """Connects to the central classroom broker network."""
        if self.debug:
            print(f"Connecting to MQTT broker at {self.broker}...")
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def disconnect(self):
        """Safely tears down the active network broker connections."""
        if self.debug: 
            print("\nStopping streaming engine...")
        self.client.loop_stop()
        self.client.disconnect()

    def broadcast(
        self,
        payload
    ):
        self.client.publish(self.topic, json.dumps(payload))


def stream_csv(streamer: MQTTStreamer, csv_path: str, tick_rate_seconds: int):
    """Send data rows from an active CSV file to MQTTStreamer at every `tick_rate_seconds` second.
    """
    if not os.path.exists(csv_path):
        print(f"Error: Target CSV file '{csv_path}' not found!")
        return

    print(f"Mode: CSV Streaming File ({csv_path}) running...")
    tot_row_sent = 0
    with open(csv_path, mode="r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        
        for row in reader:
            try:
                streamer.broadcast(row)
                tot_row_sent += 1
                time.sleep(tick_rate_seconds)
                if tot_row_sent % 10 == 0:
                    print(f"Total records sent: {tot_row_sent}")
            except (ValueError, KeyError) as err:
                print(f"Skipping malformed CSV row data: {err}")
                continue
    print(f"All data sent to MQTT Broker. Total records sent: {tot_row_sent}.")


def simulate_pv_telemetry(
    mqtt_server: str, mqtt_port: int, mqtt_topic: str, mqtt_user: str, mqtt_password, 
    csv_path: str, tick_rate_seconds=3, debug=True
):
    mqtt_streamer = MQTTStreamer(
        broker=mqtt_server, 
        port=mqtt_port,
        topic=mqtt_topic,
        username=mqtt_user,
        password=mqtt_password, 
        debug=debug
    )
    mqtt_streamer.connect()
    
    stream_csv(
        streamer=mqtt_streamer, csv_path=csv_path, tick_rate_seconds=tick_rate_seconds
    )
    
    mqtt_streamer.disconnect()    

if __name__=="__main__":
    simulate_pv_telemetry(
        mqtt_server="158.108.97.25", 
        mqtt_port=1883,
        mqtt_topic='plant/01/pv',
        mqtt_user='plant_mqtt',
        mqtt_password='SolarClass2026',
        csv_path='summer_15min.csv',
        tick_rate_seconds=1, 
    )
