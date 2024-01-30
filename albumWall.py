import configparser
import threading
import time
from flask import Flask, request, jsonify, abort
from rpi_ws281x import PixelStrip, Color
import inspect
import argparse

# Debug flag
parser = argparse.ArgumentParser(description='Dynamic LED Album Wall')
parser.add_argument('--debug', action='store_true', help='Enable debug logs')

# Flask App
app = Flask(__name__)

# String normalization
CLEAR_NON_ALPHANUMERIC_CHARS = lambda s: (''.join(char.lower() \
                                          for char in s \
                                          if char.isalnum() or char.isspace())) \
                                          if s is not None \
                                          else None

# LED strip configuration:
LED_COUNT = 91            # Number of LED pixels.
LED_PIN = 18              # GPIO Pin to which the LED strip is connected.
LED_FREQ_HZ = 800000      # LED signal frequency in hertz (usually 800kHz).
LED_DMA = 10              # DMA channel to use for generating signal (try 10).
LED_BRIGHTNESS = 255      # Set to 0 for darkest and 255 for brightest.
LED_INVERT = False        # True to invert the signal (when using NPN transistor level shift).
LED_WIPE_INTERVAL_MS = 11 # When wiping all LEDs, this is the delay between wiping each pixel (in ms)

# Initialize LED strip
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
strip.begin()

# Define thread-related variables
G_AMBIENT_RGB_STOP_EVENT = None
G_AMBIENT_RGB_THREAD = None

# Global variables to track state of LED strip
G_LED_STATUS = "off"
G_IS_ALBUM_HIGHLIGHTED = False
G_SELECTED_ARTIST = ""
G_SELECTED_ALBUM = ""
G_SELECTED_LED_START_INDEX = 0
G_SELECTED_LED_END_INDEX = 0


################################################################################
#                                DEBUG/CONFIG                                  #
################################################################################

def LOG(*args, **kwargs):
  """
     Debug logger which prints the provided statement + signature
     of function in which it was called.
  """

  # Do not print anything if not in debug
  if not app.debug:
    return

  frame = inspect.currentframe().f_back

  # Extract the function name and arguments from the frame
  function_name = frame.f_code.co_name
  argspec = inspect.getfullargspec(frame.f_globals[function_name])
  args_values = [f"{arg}={repr(frame.f_locals[arg])}" for arg in argspec.args]
  
  # Construct the function signature
  function_signature = f"{function_name}({', '.join(args_values)})"
  
  # Print the function signature along with the provided arguments
  print(f"{function_signature}: {' '.join(map(str, args))}", **kwargs)

################################################################################

def loadConfig():
  """
     Load the albums.ini config file. This function will return an array
     of dictionaries, where each dictionary represents the config data.
  """
  LOG("Attempting to load album config...")

  config = configparser.ConfigParser()
  config.read("albums.ini")

  albums = []

  for section in config.sections():
    albumDict = {}

    albumDict["albumName"] = CLEAR_NON_ALPHANUMERIC_CHARS(config.get(section, "albumName"))
    albumDict["artistName"] = CLEAR_NON_ALPHANUMERIC_CHARS(config.get(section, "artistName"))
    albumDict["ledStartIndex"] = config.get(section, "ledStartIndex")
    albumDict["ledEndIndex"] = config.get(section, "ledEndIndex")

    albums.append(albumDict)

  LOG("Album config loaded successfully!")
  return albums


################################################################################
#                             GENERIC LED CONTROL                              #
################################################################################

def colorWipe(color, firstLED=0, lastLED=strip.numPixels(), reverse=False):
  """
     Wipe color across LEDs, one light at a time.

     LEDs are connected backwards in my setup (right to left), so logic
     is flipped. "reverse=True" wipes from firstLED to lastLED,
     and "reverse=False" wipes from lastLED to firstLED.
  """

  LOG("Attempting color wipe...")
  LOG(f"Wiping from {firstLED} to {lastLED}") if not reverse else LOG(f"Wiping from {lastLED} to {firstLED}")

  # Set range to iterate over based on 'reverse' argument
  start, end, step = (lastLED, firstLED - 1, -1) if not reverse else (firstLED, lastLED + 1, 1)

  for i in range(start, end, step):
    strip.setPixelColor(i, color)
    strip.show()
    time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

  LOG("Color wipe succeeded!")

################################################################################

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

################################################################################

def turnOnAmbientRgb():
  """
     Turn on the LEDs in ambient RGB mode.

     There are a few cases here.
         1) There is an album highlighted on the wall.
         2) Ambient RGB mode animation is currently running.
         3) Lights are off.
     For case #1, we should first clear the album, and then start ambient RGB mode.
     For case #2, we should do nothing, and continue as-is.
     For case #3, we should begin ambient RGB mode.
  """

  LOG("Attempting to turn on LEDs...")

  global G_LED_STATUS
  global G_AMBIENT_RGB_THREAD
  global G_AMBIENT_RGB_STOP_EVENT

  # If there's an album selected, clear it
  clearAlbumIfHighlighted()

  # Turn on RGB Ambient mode, if not already on
  if not G_AMBIENT_RGB_THREAD and not G_AMBIENT_RGB_STOP_EVENT:
    # Color wipe rainbow to begin for a smoother transition to ambient RGB
    for i in range(strip.numPixels(), -1, -1):
      strip.setPixelColor(i, wheel((int(i * 256 / strip.numPixels()) + 1) & 255))
      strip.show()
      time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)
    # Begin ambient RGB thread
    G_AMBIENT_RGB_STOP_EVENT = threading.Event()
    G_AMBIENT_RGB_THREAD = threading.Thread(target=ambientRgbWorker, \
                                            args=(G_AMBIENT_RGB_STOP_EVENT,))
    G_AMBIENT_RGB_THREAD.start()
    LOG("Started ambient RGB.")

  G_LED_STATUS = "on"
  LOG("LEDs turned on successfully!")

################################################################################

def turnOff():
  """
     Turn off LEDs.

     There are a few cases here.
         1) Ambient RGB mode is currently running.
         2) There is an album highlighted on the wall.
     For case #1, stop ambient RGB mode. Then, clear all lights in reverse.
     For case #2, clear the highlighted album indicies only (in reverse).
  """

  LOG("Attempting to turn off LEDs...")

  global G_LED_STATUS
  global G_IS_ALBUM_HIGHLIGHTED
  global G_AMBIENT_RGB_THREAD
  global G_AMBIENT_RGB_STOP_EVENT

  # Kill ambient RGB if running
  if G_AMBIENT_RGB_THREAD and G_AMBIENT_RGB_THREAD.is_alive():
    G_AMBIENT_RGB_STOP_EVENT.set()
    G_AMBIENT_RGB_THREAD.join()
    G_AMBIENT_RGB_THREAD = None
    G_AMBIENT_RGB_STOP_EVENT = None
    LOG("Killed ambient RGB.")

  if G_IS_ALBUM_HIGHLIGHTED:
    clearAlbumIfHighlighted()
  else:
    # Turn off all LEDs in reverse
    colorWipe(Color(0, 0, 0), reverse=True)

  G_LED_STATUS = "off"
  LOG("LEDs turned off successfully!")

################################################################################

def ambientRgbWorker(stopEvent):
  """
     Draw rainbow animation that uniformly distributes itself across all pixels.
     Loop this animation repeatedly until a stopEvent is set.
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
        strip.setPixelColor(i, wheel((int(i * 256 / strip.numPixels()) + j) & 255))
      strip.show()
      time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

  LOG("Ambient RGB mode stopped successfully!")


################################################################################
#                                 ALBUM-RELATED                                #
################################################################################

def clearAlbumIfHighlighted():
  """
     If there's an album currently highlighted, clear it in reverse.
     This resets the global state variables for the currently highlighted album.
  """

  LOG("Checking to see if album is currently highlighted...")

  global G_LED_STATUS
  global G_IS_ALBUM_HIGHLIGHTED
  global G_SELECTED_ARTIST
  global G_SELECTED_ALBUM
  global G_SELECTED_LED_START_INDEX
  global G_SELECTED_LED_END_INDEX

  print(G_LED_STATUS)
  print(G_IS_ALBUM_HIGHLIGHTED)
  print(G_SELECTED_ARTIST)
  print(G_SELECTED_ALBUM)
  print(G_SELECTED_LED_START_INDEX)
  print(G_SELECTED_LED_END_INDEX)

  if G_IS_ALBUM_HIGHLIGHTED:
    LOG("Album currently highlighted, clearing first.")

    # Clear the album
    colorWipe(Color(0, 0, 0), \
              G_SELECTED_LED_START_INDEX, \
              G_SELECTED_LED_END_INDEX, \
              reverse=True)

    # Reset global state variables for the currently highlighted album
    G_LED_STATUS = "off"
    G_IS_ALBUM_HIGHLIGHTED = False
    G_SELECTED_ARTIST = ""
    G_SELECTED_ALBUM = ""
    G_SELECTED_LED_START_INDEX = 0
    G_SELECTED_LED_END_INDEX = 0

  else:
    LOG("No album highlighted, continuing.")

################################################################################

def highlightAlbum(ledStartIndex, ledEndIndex):
  """
     Turn LEDs off, then highlight the album in white within provided index range.
  """

  LOG("Attempting to highlight album...")

  global G_LED_STATUS

  # Highlight album in white
  colorWipe(Color(255, 255, 255), ledStartIndex, ledEndIndex)

  G_LED_STATUS = "on"

  LOG("Album highlighted successfully!")

################################################################################

def handlePossibleAlbumMatch(artistName, albumName):
  """
     Given an artistName and albumName, search the wall for a match.
     This API will succeed if a match is found or not - a match is
     not required for this app to work.
  """

  LOG("Attempting to find an album match...")

  found = False
  global G_SELECTED_ARTIST
  global G_SELECTED_ALBUM
  global G_SELECTED_LED_START_INDEX
  global G_SELECTED_LED_END_INDEX
  global G_IS_ALBUM_HIGHLIGHTED

  if artistName is None or albumName is None:
    # Both must be set for this function to run
    return False

  # If currently playing album is already highlighted, do nothing
  if G_IS_ALBUM_HIGHLIGHTED and \
     G_SELECTED_ARTIST == artistName and \
     G_SELECTED_ALBUM == albumName:
    LOG("Album already highlighted, doing nothing.")
    return True
  
  # This processes the provided albums.ini file into an array of dictionaries
  wallAlbums = loadConfig()
  
  # Search for a match within albums on the wall
  for album in wallAlbums:
    # If there is a match, highlight the album on the wall
    LOG(f"Checking match against {album['albumName']} by {album['artistName']}")
    if album["artistName"] == artistName and album["albumName"] == albumName:
      LOG("Match found!")
      found = True
      turnOff()
      G_SELECTED_ARTIST = artistName
      G_SELECTED_ALBUM = albumName
      G_SELECTED_LED_START_INDEX = int(album["ledStartIndex"])
      G_SELECTED_LED_END_INDEX = int(album["ledEndIndex"])
      G_IS_ALBUM_HIGHLIGHTED = True
      highlightAlbum(G_SELECTED_LED_START_INDEX, G_SELECTED_LED_END_INDEX)
      break
    LOG("No match, continuing search...")

  LOG("Album match search finished!")
  return found


################################################################################
#                                  FLASK APIS                                  #
################################################################################

@app.route("/ledStatus", methods=["GET"])
def ledStatus():
  """
     Return status of LEDs
  """

  LOG("Returning LED Status")
  global G_LED_STATUS

  return jsonify({"message": "Success!", "ledStatus": G_LED_STATUS}), 200

################################################################################

@app.route("/albumWall", methods=['GET', 'POST'])
def albumWall():
  """
     Main handler for album wall control
  """

  data = request.get_json()

  LOG("Retrieved data:")
  LOG(data)

  global G_LED_STATUS
  global G_IS_ALBUM_HIGHLIGHTED
  global G_SELECTED_ARTIST
  global G_SELECTED_ALBUM

  # Parse incoming JSON data
  ledStatus = data.get("ledStatus")
  artistName = data.get("artistName")
  albumName = data.get("albumName")
  playbackEvent = data.get("playbackEvent")

  # Clean up variables
  artistName = CLEAR_NON_ALPHANUMERIC_CHARS(artistName)
  albumName = CLEAR_NON_ALPHANUMERIC_CHARS(albumName)

  LOG(f'Processing "{playbackEvent}" playback event')

  LOG(f'Album currently highlighted = {G_IS_ALBUM_HIGHLIGHTED}')
  if G_IS_ALBUM_HIGHLIGHTED:
    LOG(f'Currently selected artist = {G_SELECTED_ARTIST}')
    LOG(f'Currently selected album = {G_SELECTED_ALBUM}')

  # Argument validity check
  # ledStatus must be one of "on" or "off"
  # Either both or neither of artistName and albumName should be set
  if (artistName is None and albumName is not None) or \
     (artistName is not None and albumName is None) or \
     (ledStatus != "on" and ledStatus != "off"):
    abort(400)
  
  # Turn off LEDs. Tautulli considers a track change as playback stop event,
  # so ensure that nothing is playing before turning off.
  # Without this check, the LEDs power cycle between every track.
  if ledStatus == "off" and artistName is None and albumName is None:
    LOG("Attempting to turn off LEDs...")
    if ledStatus != G_LED_STATUS:
      LOG("LEDs on, turning off...")
      turnOff()
    LOG("LEDs turned off!")

  # Turn on LEDs
  elif ledStatus == "on":
    # First, we determine whether or not the currently playing album matches
    # an album on the wall.
    # If there's a match, handlePossibleAlbumMatch will highlight the album.
    # If not, we should execute the normal turnOnAmbientRgb function.

    albumFound = handlePossibleAlbumMatch(artistName, albumName)

    if not albumFound:
      ret = turnOnAmbientRgb()

  LOG("Request processed successfully!")
  return jsonify({"message": "Success!"}), 200


################################################################################
################################################################################


if __name__ == "__main__":
  # Check for debug flag
  args = parser.parse_args()
  app.debug = True if args.debug else False

  # Start single-threaded flask app to avoid race conditions.
  # No advantage to multithreading in this app, only headaches.
  app.run(host="0.0.0.0", port=80, threaded=False)

