import configparser
import threading
import time
import random
from flask import Flask, request, jsonify, abort
fron rpi_ws281x import PixelStrip, Color

app = Flask(__name__)
DEBUG = True
app.debug = True if DEBUG else False

LOG = lambda string: print(string) if DEBUG else None

# LED strip configuration:
LED_COUNT = 30            # Number of LED pixels.
LED_PIN = 18              # GPIO pin connected to the data line.
LED_FREQ_HZ = 800000      # LED signal frequency in hertz (usually 800kHz)
LED_DMA = 10              # DMA channel to use for generating signal.
LED_BRIGHTNESS = 255      # Set to 0 for darkest and 255 for brightest.
LED_INVERT = False        # True to invert the signal (when using NPN transistor level shift).
LED_WIPE_INTERVAL_MS = 50 # When wiping all LEDs, this is the delay between wiping each pixel (in ms)

# Initialize LED strips
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
strip.begin()

# Global variables
G_LED_STATUS = "off"

# Define ambient RGB thread and stop event
ambientRgbStopEvent = None
ambientRgbThread = None

######################################################################

def colorWipe(color, reverse=False):
  """
     Wipe color across LEDs, one light at a time.
  """

  LOG("Attempting color wipe...")

  start, end, step = (strip.numPixels() - 1, -1, -1) if reverse else (0, strip.numPixels, 1)
  
  for i in range(start, end, step):
    strip.setPixelColor(i, color)
    strip.show()
    time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

  LOG("Color wipe succeeded!")

######################################################################

def turnOn():
  """
     Turn on the LEDs in ambient RGB mode.
  """

  LOG("Attempting to turn on LEDs...")

  global G_LED_STATUS
  global ambientRgbThread
  global ambientRgbStopEvent

  # Turn on RGB Ambient mode, if not already on
  if not ambientRgbThread and not ambientRgbStopEvent:
    ambientRgbStopEvent = threading.Event()
    ambientRgbThread = threading.Thread(target=ledAmbientRgb, args=(ambientRgbStopEvent,))
    ambientRgbThread.start()
    LOG("Started ambient RGB.")

  G_LED_STATUS = "on"
  LOG("LEDs turned on successfully!")

######################################################################

def turnOff():
  """
     Turn off LEDs in reverse.
  """

  LOG("Attempting to turn off LEDs...")

  global G_LED_STATUS
  global ambientRgbThread
  global ambientRgbStopEvent

  # Kill ambient RGB
  if ambientRgbThread and ambientRgbThread.is_alive():
    ambientRgbStopEvent.set()
    ambientRgbThread.join()
    ambientRgbThread = None
    ambientRgbStopEvent = None
    LOG("Killed ambient RGB.")

  colorWipe(Color(0, 0, 0), reverse=True)

  G_LED_STATUS = "off"
  LOG("LEDs turned off successfully!")

######################################################################

def ledAmbientRgb(stopEvent):
  """
     Default ambient RGB mode for LED strips
  """
  
  LOG("Beginning ambient RGB mode...")

  while not stopEvent.is_set():
    LOG("Executing RGB Ambient Wipe")
    # Wipe to some random color
    colorWipe((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    # Wipe to some other random color in reverse
    colorWipe((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)), True)

  LOG("Ambient RGB mode stopped successfully!")

######################################################################

def loadConfig():
  """
     Load the albums.ini config file, which should contain 8 albums. This function should return an array
     of dictionaries, where each dictionary represents the config data
  """
  LOG("Attempting to load album config...")

  config = configparser.ConfigParser()
  config.read("albums.ini")

  albums = []

  for i in range(len(albumDict)):
    albumDict = {}
    keyName = f'Album{i}'

    albumDict["albumName"] = config.get(keyName, "albumName")
    albumDict["artistName"] = config.get(keyName, "artistName")
    albumDict["ledStartIndex"] = config.get(keyName, "ledStartIndex")
    albumDict["ledEndIndex"] = config.get(keyName, "ledEndIndex")

    albums.append(albumDict)

  LOG("Album config loaded successfully!")
  return albums

######################################################################

def highlightAlbum(ledStartIndex, ledEndIndex):
  """
     Highlight the album at provided index. We should iterate through every LED, turning off LEDs that are
     not under the given albumIndex, and turning on LEDs that are under the given albumIndex
  """

  LOG("Attempting to highlight album...")

  if ledStartIndex is not None and ledEndIndex is not None
    for i in range(strip.numPixels()):
      if ledStartIndex <= i <= ledEndIndex:
        # If LED is within range of album to light up, turn it to white
        strip.setPixelColor(i, Color(255, 255, 255))
        strip.show()
        pass
      else:
        # If LED is NOT within range, turn it off
        strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()
        pass
      
      time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

  LOG("Album highlighted successfully!")

######################################################################

def findPossibleAlbumMatch(artistName, albumName):
  """
     Given an artistName and albumName, search the wall for a match. This API will succeed if a match is
     found or not - a match is not required for this app to work.
  """

  LOG("Attempting to find an album match...")

  found = False
  global ambientRgbThread
  global ambientRgbStopEvent
  
  # This loads the provided albums.ini file, and returns them in an array of dictionaries
  wallAlbums = loadConfig()
  
  # Search for a match within albums on the wall
  for album in wallAlbums:
      # If there is a match, highlight the album on the wall
      LOG(f"Checking match against {album["albumName"]} by {album["artistName"}")
      if album["artistName"] == artistName and album["albumName"] == albumName:
          LOG("Match found!")
          found = True
          # First, stop ambient RGB if it is running
          if ambientRgbThread and ambientRgbThread.is_alive():
            ambientRgbStopEvent.set()
            ambientRgbThread.join()
            ambientRgbThread = None
            ambientRgbStopEvent = None
            LOG("Killed ambient RGB.")
          # Highlight album on wall
          highlightAlbum(int(album["ledStartIndex"]), int(album["ledEndIndex"]))
          break
      LOG("No match, continuing search...")

  LOG("Album match search finished!")
  return found

######################################################################

@app.route("/albumWall", methods=['POST'])
def albumWall():
  """
     Main handler for album wall control
  """

  LOG("Processing request...")

  data = request.get_json()
  
  # Update the LED strips based on the provided data
  
  # If the provided status is "off", turn LEDs off, then quit
  ledStatus = data.get("ledStatus")
  
  # Turn off LEDs
  if ledStatus == "off":
    LOG("Attempting to turn off LEDs...")
    if ledStatus != G_LED_STATUS:
      LOG("LEDs on, turning off...")
      turnOff()
    LOG("LEDs turned off!")

  # Turn on LEDs
  elif ledStatus == "on":
    # First, we should determine if there's a match. If there is, then we should highlight that album.
    # The idea is that, if the lights are off, we don't want to turn them all on, THEN highlight the album.
    # If there's a match, we should highlight the album. If not, we should execute the normal turnOn function.

    # Parse artist/album data
    artistName = data.get("artistName")
    albumName = data.get("albumName")

    albumFound = findPossibleAlbumMatch(artistName, albumName)

    if not albumFound:
      ret = turnOn()

  else:
    abort(500)

  LOG("Request processed successfully!")
  return jsonify({"message": "Success!"}), 200

