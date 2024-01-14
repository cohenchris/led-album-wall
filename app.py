import configparser
import threading
import time
import random
from flask import Flask, request, jsonify, abort
from rpi_ws281x import PixelStrip, Color
import re

app = Flask(__name__)
DEBUG = False
app.debug = True if DEBUG else False

LOG = lambda string: print(string) if DEBUG else None

CLEAR_NON_ALPHANUMERIC_CHARS = lambda string: re.sub(r'[^a-zA-Z0-9\s]', '', string)

# LED strip configuration:
LED_COUNT = 91            # Number of LED pixels.
LED_PIN = 18              # GPIO Pin to which the 'B' input is connected
LED_FREQ_HZ = 800000      # LED signal frequency in hertz (usually 800kHz)
LED_DMA = 10              # DMA channel to use for generating signal.
LED_BRIGHTNESS = 255      # Set to 0 for darkest and 255 for brightest.
LED_INVERT = False        # True to invert the signal (when using NPN transistor level shift).
LED_WIPE_INTERVAL_MS = 20 # When wiping all LEDs, this is the delay between wiping each pixel (in ms)

# Initialize LED strips
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
strip.begin()

# Global variables
G_LED_STATUS = "off"
G_SELECTED_ARTIST = ""
G_SELECTED_ALBUM = ""

# Define ambient RGB thread and stop event
ambientRgbStopEvent = None
ambientRgbThread = None

######################################################################

def colorWipe(color, start=0, end=strip.numPixels()):
  """
     Wipe color across LEDs, one light at a time.
  """

  LOG("Attempting color wipe...")
  LOG(f"Wiping from {start} to {end}")

  for i in range(end, start - 1, -1):
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

  colorWipe(Color(0, 0, 0))
  colorWipe(Color(255, 255, 255))

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
     Turn off LEDs
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

  colorWipe(Color(0, 0, 0))

  G_LED_STATUS = "off"
  LOG("LEDs turned off successfully!")

######################################################################

def wheel(pos):
    """
       Generate rainbow colors across 0-255 positions.
    """

    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

######################################################################

def ledAmbientRgb(stopEvent):
  """
     Draw rainbow that uniformly distributes itself across all pixels.
  """
  
  LOG("Beginning ambient RGB mode...")
  iterations = 5

  while not stopEvent.is_set():
    LOG("Executing RGB ambient animation")
    for j in range(256 * iterations):
        if stopEvent.is_set():
          break

        for i in range(strip.numPixels()):
            if stopEvent.is_set():
                break
            strip.setPixelColor(i, wheel(
                (int(i * 256 / strip.numPixels()) + j) & 255))

        strip.show()
        time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

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

  for section in config.sections():
    albumDict = {}

    albumDict["albumName"] = config.get(section, "albumName")
    albumDict["artistName"] = config.get(section, "artistName")
    albumDict["ledStartIndex"] = config.get(section, "ledStartIndex")
    albumDict["ledEndIndex"] = config.get(section, "ledEndIndex")

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

  # Turn all LEDs off
  turnOff()

  # Highlight album in white
  colorWipe(Color(255, 255, 255), ledStartIndex, ledEndIndex)

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
  global G_SELECTED_ARTIST
  global G_SELECTED_ALBUM

  if artistName is None or albumName is None:
    # Both must be set for this function to run
    return found
  
  # This loads the provided albums.ini file, and returns them in an array of dictionaries
  wallAlbums = loadConfig()
  
  # Search for a match within albums on the wall
  for album in wallAlbums:
      # Clean up strings
      album['albumName'] = CLEAR_NON_ALPHANUMERIC_CHARS(album['albumName'])
      album['artistName'] = CLEAR_NON_ALPHANUMERIC_CHARS(album['artistName'])
      artistName = CLEAR_NON_ALPHANUMERIC_CHARS(artistName)
      albumName = CLEAR_NON_ALPHANUMERIC_CHARS(albumName)

      # If there is a match, highlight the album on the wall
      LOG(f"Checking match against {album['albumName']} by {album['artistName']}")
      if album["artistName"] == artistName and album["albumName"] == albumName:
          LOG("Match found!")
          found = True
          # Highlight album on wall
          if G_SELECTED_ARTIST != artistName and G_SELECTED_ALBUM != albumName:
            highlightAlbum(int(album["ledStartIndex"]), int(album["ledEndIndex"]))
            G_SELECTED_ARTIST = artistName
            G_SELECTED_ALBUM = albumName
          break
      LOG("No match, continuing search...")

  LOG("Album match search finished!")
  return found

######################################################################

@app.route("/ledStatus", methods=["GET"])
def ledStatus():
  """
     Return status of LEDs
  """
  LOG("Returning LED Status")
  return jsonify({"message": "Success!", "ledStatus": G_LED_STATUS}), 200

######################################################################

@app.route("/albumWall", methods=['POST'])
def albumWall():
  """
     Main handler for album wall control
  """

  LOG("Processing request...")

  data = request.get_json()

  LOG("Retrieved data:")
  LOG(data)
  
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

    if (artistName is None and albumName is not None) or (artistName is not None and albumName is None):
      # Either both should be set, or neither should be set.
      abort(400)

    albumFound = findPossibleAlbumMatch(artistName, albumName)

    if not albumFound:
      ret = turnOn()

  else:
    abort(400)

  LOG("Request processed successfully!")
  return jsonify({"message": "Success!"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
