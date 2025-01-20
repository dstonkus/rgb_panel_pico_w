import board
import displayio
import framebufferio
import rgbmatrix
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font
from displayio import Bitmap
import wifi
import ssl
import socketpool
import adafruit_requests
import time
import microcontroller
import os
import adafruit_ntp
import gc
import adafruit_json_stream as json_stream

# Configuration
WIFI_SSID = os.getenv('CIRCUITPY_WIFI_SSID')
WIFI_PASSWORD = os.getenv('CIRCUITPY_WIFI_PASSWORD')
MINUTES_30 = 30 * 60  # 1800 seconds

class NetworkManager:
    def __init__(self, ssid, password):
        self.ssid = ssid
        self.password = password
        self.pool = None
        self.requests = None
        self.is_connected = False
        self.ntp = None
        self.last_ntp_sync = 0
        self.ntp_sync_interval = 3600  # Sync every hour
    
    def connect(self):
        if self.is_connected and wifi.radio.connected:
            return True
        
        try:
            wifi.radio.connect(self.ssid, self.password)
            self.pool = socketpool.SocketPool(wifi.radio)
            self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())
            self.is_connected = True
            self.ntp = adafruit_ntp.NTP(self.pool, tz_offset=2)
            return True
        except Exception as e:
            self.is_connected = False
            return False
        
    def get_current_time(self):
        try:
            if self.ntp:
                current = time.monotonic()
                if current - self.last_ntp_sync >= self.ntp_sync_interval:
                    print("Getting fresh NTP time...")
                    self.last_ntp_sync = current
                return self.ntp.datetime
        except Exception as e:
            print(f"NTP time error: {e}")
        return None

    def get_session(self):
        return self.requests if self.is_connected else None
    

def create_cloud_icon():
    # Create a 12x8 bitmap for the cloud
    cloud_bitmap = displayio.Bitmap(20, 12, 5)
    
    # Color palette
    cloud_palette = displayio.Palette(5)
    cloud_palette[0] = 0x000000  # Black/transparent
    cloud_palette[1] = 0xFFFFFF  # Bright white
    cloud_palette[2] = 0x9EB4FF  # Medium bright blue
    cloud_palette[3] = 0x4169E1  # Royal blue
    cloud_palette[4] = 0x1E3B8C  # Dark navy blue
    
    # Eloud pattern
    # 0 = transparent
    # 1 = pure white (highlights)
    # 2 = light lavender (upper surface)
    # 3 = light steel blue (mid tones)
    # 4 = original blue (lower surface)
    # 5 = dark blue (shadows)

    cloud_pattern = [
        [0,0,0,0,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,1,1,1,1,1,1,2,2,2,0,0,0,0,0,0,0,0],
        [0,0,1,1,1,1,1,1,2,2,2,2,2,2,0,0,0,0,0,0],
        [0,1,1,1,1,1,1,2,2,2,2,2,2,2,3,3,3,0,0,0],
        [1,1,1,1,1,2,2,2,2,2,2,2,3,3,3,3,3,3,0,0],
        [1,1,2,2,2,2,2,2,2,2,2,3,3,3,3,3,3,3,3,0],
        [0,2,2,2,3,3,3,3,3,3,3,3,3,4,4,4,4,4,0,0],
        [0,0,3,3,3,3,3,3,3,3,3,4,4,4,4,4,4,0,0,0],
        [0,0,0,0,3,3,3,4,4,4,4,4,4,4,4,0,0,0,0,0],
        [0,0,0,0,0,4,4,4,4,4,4,4,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
    ]
    
    # Transfer the pattern to the bitmap
    for y in range(len(cloud_pattern)):
        for x in range(len(cloud_pattern[0])):
            cloud_bitmap[x, y] = cloud_pattern[y][x]
    
    # Create the TileGrid
    cloud_grid = displayio.TileGrid(cloud_bitmap, pixel_shader=cloud_palette)
    
    # Create a group for the cloud
    cloud_group = displayio.Group()
    cloud_group.append(cloud_grid)
    
    return cloud_group
    
class WeatherClockDisplay:
    def __init__(self, network_manager):
        self.network_manager = network_manager
        self.update_interval = 1
        self.font = bitmap_font.load_font("/fonts/6x10.bdf", Bitmap)
        self.small_font = bitmap_font.load_font("/fonts/4x6.bdf", Bitmap)
        
        # Add a separator state variable
        self.separator_visible = True
        self.last_separator_toggle = time.monotonic()
        self.separator_interval = 1 # Second
        
        # Weather check timing
        self.last_time_weather_check = 0
        self.weather_check_interval = MINUTES_30
        self.weather_data = None
        self.first_fetch = True
        
        # Weekdays
        self.weekdays = ["Pirm", "Antr", "Trec", "Ketv", "Penkt", "Sest", "Sekm"]
                
        # Setup display
        self.setup_display()
        
    def setup_display(self):
        displayio.release_displays()
        matrix = rgbmatrix.RGBMatrix(
            width=64, height=32, bit_depth=3,
            rgb_pins=[board.GP2, board.GP3, board.GP4, board.GP5, board.GP8, board.GP9],
            addr_pins=[board.GP10, board.GP16, board.GP18, board.GP20],
            clock_pin=board.GP11, latch_pin=board.GP12, output_enable_pin=board.GP13,
            tile=1, serpentine=False, doublebuffer=True
        )
        self.display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True, rotation=180)
        
        # Create main display group
        self.main_group = displayio.Group()
        self.display.root_group = self.main_group
        
        # Setup clock display
        self.setup_clock_display()
        
    def setup_clock_display(self):
        self.palette = displayio.Palette(6)
        self.palette[0] = 0x000000  # Black background
        self.palette[1] = 0xFFFFFF  # White for text
        self.palette[2] = 0xFF0000  # Red
        self.palette[3] = 0x01949A  # Teal
        self.palette[4] = 0x86ffa2  # Light Greeeenish
        self.palette[5] = 0x8693ff  # Light Purplish Blueish
    
        self.clock_group = displayio.Group()
        self.main_group.append(self.clock_group)
        
        # Clock label
        self.time_label = Label(self.font, color=0xFF0000, text="00:00")
        self.time_label.x = 0
        self.time_label.y = 4
        self.clock_group.append(self.time_label)
        

        # Cloud
        self.cloud_icon = create_cloud_icon()
        self.cloud_icon.x = 38  # Same x position as previous text
        self.cloud_icon.y = 0   # Adjust y position as needed
        self.clock_group.append(self.cloud_icon)
        
        # Middle top label
        #background_color=0xFF00FF
        self.middle_top_left_row_label = Label(self.small_font, color=0x8693ff, text="...")
        self.middle_top_left_row_label.x = 0
        self.middle_top_left_row_label.y = 12
        self.clock_group.append(self.middle_top_left_row_label)
        
        # Middle top right label
        #background_color=0xFF00FF
        self.middle_top_right_row_label = Label(self.small_font, color=0x01949A, text="...")
        self.middle_top_right_row_label.x = 20
        self.middle_top_right_row_label.y = 12
        self.clock_group.append(self.middle_top_right_row_label)
        
        # Middle row label
        #background_color=0xFF00FF
        self.weather_label = Label(self.small_font, color=0x86ffa2, text="...")
        self.weather_label.x = 0
        self.weather_label.y = 20
        self.clock_group.append(self.weather_label)
        
        # Bottom row label
        self.bottom_row_label = Label(self.small_font, color=0x01949A, text="............................")
        self.bottom_row_label.x = 0
        self.bottom_row_label.y = 28
        self.clock_group.append(self.bottom_row_label)
        

    def fetch_weather(self):
        session = self.network_manager.get_session()
        if session:
            gc.collect()
            try:
                resp = session.get('https://api.meteo.lt/v1/places/vilnius/forecasts/long-term')
                json_data = json_stream.load(resp.iter_content(32))
                
                current_time = self.network_manager.get_current_time()
                forecast = self.get_current_hour_forecast(json_data, current_time)
                
                if forecast['condition'] == 'cloudy':
                    forecast['condition'] = 'Debesuota'
                
                if forecast:
                    self.weather_label.text = f"{forecast['temperature']:.1f}°c     {forecast['feels_like']:.1f}°c"
                
                self.last_time_weather_check = time.monotonic()
            except Exception as e:
                print(f"Weather fetch error: {e}")
            
    def get_current_hour_forecast(self, weather_data, current_time):
        if not current_time:
            return None
            
        current_hour = current_time.tm_hour
        current_date = f"{current_time.tm_year}-{current_time.tm_mon:02d}-{current_time.tm_mday:02d}"
        
        for forecast in weather_data['forecastTimestamps']:
            forecast_datetime = forecast['forecastTimeUtc'].split()
            forecast_date = forecast_datetime[0]
            forecast_hour = int(forecast_datetime[1].split(':')[0])
            
            if forecast_date == current_date and forecast_hour == current_hour:
                return {
                    'temperature': forecast['airTemperature'],
                    'condition': forecast['conditionCode'],
                    'wind_speed': forecast['windSpeed'],
                    'humidity': forecast['relativeHumidity'],
                    'feels_like': forecast['feelsLikeTemperature']
                }
        return None
            
    def update_display(self):
        current_time = self.network_manager.get_current_time()
        
        if current_time:
            weekday_name = self.weekdays[current_time.tm_wday]
            
            self.middle_top_left_row_label.text = f"{weekday_name}"
            self.middle_top_right_row_label.text = f"{current_time.tm_mon:02d}.{current_time.tm_mday:02d}"
            # Check if it's time to toggle the separator
            current = time.monotonic()
            if current - self.last_separator_toggle >= self.separator_interval:
                self.separator_visible = not self.separator_visible
                self.last_separator_toggle = current
            
            # Use : or space depending on separator visibility
            separator = ":" if self.separator_visible else " "
            
            # Format time with the dynamic separator
            self.time_label.text = f"{current_time.tm_hour:02d}{separator}{current_time.tm_min:02d}"
            
        
        # Initial weather fetch
        if self.first_fetch and self.network_manager.is_connected:
            print("Initial weather fetch triggered")
            self.fetch_weather()
            self.first_fetch = False
            
        # Regular weather updates
        if time.monotonic() - self.last_time_weather_check >= self.weather_check_interval:
            print("Time to fetch weather")
            self.fetch_weather()



def main():
    try:
        # Initialize network
        network_manager = NetworkManager(WIFI_SSID, WIFI_PASSWORD)
        
        # Initialize weather clock display
        weather_clock = WeatherClockDisplay(network_manager)
        
        # Main loop
        while True:
            try:
                network_manager.connect()
                gc.collect()
                weather_clock.update_display()
                time.sleep(0.1)
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(1)
                continue

    except Exception as e:
        print(f"Fatal error: {e}")
        time.sleep(5)
        microcontroller.reset()

if __name__ == '__main__':
    main()

