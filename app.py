import configparser
import threading
import time
from flask import Flask, request, jsonify, abort, g
from rpi_ws281x import PixelStrip, Color
import inspect
import sqlite3
import os

app = Flask(__name__)
DEBUG = False
app.debug = True if DEBUG else False
app.config['DATABASE'] = "albumwall.db"

# String normalizing function - removes all non-alphanumeric chars and makes the string all lowercase
CLEAR_NON_ALPHANUMERIC_CHARS = lambda s: (''.join(char.lower() for char in s if char.isalnum() or char.isspace())) if s is not None else None

# LED strip configuration:
LED_COUNT = 91            # Number of LED pixels.
LED_PIN = 18              # GPIO Pin to which the 'B' input is connected
LED_FREQ_HZ = 800000      # LED signal frequency in hertz (usually 800kHz)
LED_DMA = 10              # DMA channel to use for generating signal.
LED_BRIGHTNESS = 255      # Set to 0 for darkest and 255 for brightest.
LED_INVERT = False        # True to invert the signal (when using NPN transistor level shift).
LED_WIPE_INTERVAL_MS = 10 # When wiping all LEDs, this is the delay between wiping each pixel (in ms)

# Initialize LED strips
strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
strip.begin()

# Define thread-related variables
ambientRgbStopEvent = None
ambientRgbThread = None





######################################################################
#                           DATABASE                                 #
######################################################################

# Global DB variable names
G_LED_STATUS = "G_LED_STATUS"
G_IS_ALBUM_HIGHLIGHTED = "G_IS_ALBUM_HIGHLIGHTED"
G_SELECTED_ARTIST = "G_SELECTED_ARTIST"
G_SELECTED_ALBUM = "G_SELECTED_ALBUM"
G_SELECTED_LED_START_INDEX = "G_SELECTED_LED_START_INDEX"
G_SELECTED_LED_END_INDEX = "G_SELECTED_LED_END_INDEX"

######################################################################

def getDb():
  if 'db' not in g:
    g.db = sqlite3.connect(app.config['DATABASE'])
  return g.db

######################################################################

@app.teardown_appcontext
def closeDb(error):
  LOG(f'DB Closing with status "{error}"')
  if hasattr(g, 'db'):
    g.db.close()

######################################################################

def initDb():
  LOG("Initializing DB...")

  global G_LED_STATUS

  db = getDb()

  with app.open_resource("albumwallschema.sql", mode="r") as f:
    db.cursor().executescript(f.read())
  db.commit()

  setGlobalVariable(G_LED_STATUS, "off")
  clearArtistDataFromDb()

  LOG("DB Initialized!")

######################################################################

def clearArtistDataFromDb():
  LOG("Clearing DB...")

  global G_IS_ALBUM_HIGHLIGHTED
  global G_SELECTED_ARTIST
  global G_SELECTED_ALBUM
  global G_SELECTED_LED_START_INDEX
  global G_SELECTED_LED_END_INDEX

  setGlobalVariable(G_IS_ALBUM_HIGHLIGHTED, "False")
  setGlobalVariable(G_SELECTED_ARTIST, "")
  setGlobalVariable(G_SELECTED_ALBUM, "")
  setGlobalVariable(G_SELECTED_LED_START_INDEX, "0")
  setGlobalVariable(G_SELECTED_LED_END_INDEX, "0")

  LOG("DB Cleared!")

######################################################################

def setGlobalVariable(name, value):
  db = getDb()

  isExisting = getGlobalVariable(name) is not None

  LOG(f"Setting {name} = {value}")

  if isExisting:
    db.execute('UPDATE variables SET value = ? WHERE name = ?', (value, name))
  else:
    db.execute('INSERT INTO variables (name, value) VALUES (?, ?)', (name, value))
  
  db.commit()

######################################################################

def getGlobalVariable(name):
  db = getDb()

  cursor = db.execute('SELECT value FROM variables WHERE name = ?', (name,))
  result = cursor.fetchone()

  LOG(f"result = {result}")

  value = result[0] if result else None

  LOG(f"Retrieved {name} = {value}")

  return value

######################################################################





######################################################################
#                            DEBUG/CONFIG                            #
######################################################################

def LOG(*args, **kwargs):
  """
     Debug logger which prints the provided statement + signature of function in which it was called
  """

  # Do not print anything if not in debug
  if not DEBUG:
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

    albumDict["albumName"] = CLEAR_NON_ALPHANUMERIC_CHARS(config.get(section, "albumName"))
    albumDict["artistName"] = CLEAR_NON_ALPHANUMERIC_CHARS(config.get(section, "artistName"))
    albumDict["ledStartIndex"] = config.get(section, "ledStartIndex")
    albumDict["ledEndIndex"] = config.get(section, "ledEndIndex")

    albums.append(albumDict)

  LOG("Album config loaded successfully!")
  return albums

######################################################################





######################################################################
#                        GENERIC LED CONTROL                         #
######################################################################

def colorWipe(color, start=0, end=strip.numPixels(), reverse=False):
  """
     Wipe color across LEDs, one light at a time.

     NOTE: LEDs are connected backwards in my setup (right to left), so logic is flipped.
           "reverse=True" wipes from 0 to end, and "reverse=False" wipes from end to 0
  """

  LOG("Attempting color wipe...")
  LOG(f"Wiping from {start} to {end}") if not reverse else LOG(f"Wiping from {end} to {start}")

  s, e, step = (end, start - 1, -1) if not reverse else (start, end + 1, 1)

  #for i in range(end, start - 1, -1):
  for i in range(s, e, step):
    strip.setPixelColor(i, color)
    strip.show()
    time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)

  LOG("Color wipe succeeded!")

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

def turnOn():
  """
     Turn on the LEDs in ambient RGB mode.
  """

  LOG("Attempting to turn on LEDs...")

  global G_LED_STATUS
  global ambientRgbThread
  global ambientRgbStopEvent

  # If there's an album selected, clear it
  clearAlbumIfHighlighted()

  # Turn on RGB Ambient mode, if not already on
  if not ambientRgbThread and not ambientRgbStopEvent:
    # Color wipe rainbow to begin for a smoother transition to ambient RGB
    for i in range(strip.numPixels(), -1, -1):
      strip.setPixelColor(i, wheel((int(i * 256 / strip.numPixels()) + 1) & 255))
      strip.show()
      time.sleep(LED_WIPE_INTERVAL_MS / 1000.0)
    # Begin ambient RGB thread
    ambientRgbStopEvent = threading.Event()
    ambientRgbThread = threading.Thread(target=ambientRgb, args=(ambientRgbStopEvent,))
    ambientRgbThread.start()
    LOG("Started ambient RGB.")

  setGlobalVariable(G_LED_STATUS, "on")
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

  # Kill ambient RGB if running
  if ambientRgbThread and ambientRgbThread.is_alive():
    ambientRgbStopEvent.set()
    ambientRgbThread.join()
    ambientRgbThread = None
    ambientRgbStopEvent = None
    LOG("Killed ambient RGB.")
  else:
    # If ambient RGB is not on, there may be an album highlighted, so clear it if so
    clearAlbumIfHighlighted()

  # Turn off all LEDs in reverse
  colorWipe(Color(0, 0, 0), reverse=True)

  setGlobalVariable(G_LED_STATUS, "off")
  LOG("LEDs turned off successfully!")


######################################################################

def ambientRgb(stopEvent):
  """
     Draw rainbow animation that uniformly distributes itself across all pixels.
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

######################################################################





######################################################################
#                           ALBUM-RELATED                            #
######################################################################

def clearAlbumIfHighlighted():
  """
     If there's an album currently highlighted, clear it in reverse
  """

  LOG("Checking to see if album is currently highlighted...")

  global G_SELECTED_LED_START_INDEX
  global G_SELECTED_LED_END_INDEX
  global G_IS_ALBUM_HIGHLIGHTED

  if getGlobalVariable(G_IS_ALBUM_HIGHLIGHTED) == "True":
    LOG("Album currently highlighted, clearing first.")
    colorWipe(Color(0, 0, 0), \
              int(getGlobalVariable(G_SELECTED_LED_START_INDEX)), \
              int(getGlobalVariable(G_SELECTED_LED_END_INDEX)), \
              reverse=True)
    clearArtistDataFromDb()
  else:
    LOG("No album highlighted, continuing.")

######################################################################

def highlightAlbum(ledStartIndex, ledEndIndex):
  """
     Turn LEDs off, then highlight the album in white within provided index range.
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
  global G_SELECTED_LED_START_INDEX
  global G_SELECTED_LED_END_INDEX
  global G_IS_ALBUM_HIGHLIGHTED

  if artistName is None or albumName is None:
    # Both must be set for this function to run
    return found

  # If currently playing album is already highlighted, do nothing
  if getGlobalVariable(G_IS_ALBUM_HIGHLIGHTED) == "True" and \
     getGlobalVariable(G_SELECTED_ARTIST) == artistName and \
     getGlobalVariable(G_SELECTED_ALBUM) == albumName:
    LOG("Album already highlighted, doing nothing.")
    found = True
    return found
  
  # This loads the provided albums.ini file, and returns them in an array of dictionaries
  wallAlbums = loadConfig()
  
  # Search for a match within albums on the wall
  for album in wallAlbums:
    # If there is a match, highlight the album on the wall
    LOG(f"Checking match against {album['albumName']} by {album['artistName']}")
    if album["artistName"] == artistName and album["albumName"] == albumName:
      LOG("Match found!")
      found = True
      setGlobalVariable(G_SELECTED_ARTIST, artistName)
      setGlobalVariable(G_SELECTED_ALBUM, albumName)
      setGlobalVariable(G_SELECTED_LED_START_INDEX, album["ledStartIndex"])
      setGlobalVariable(G_SELECTED_LED_END_INDEX, album["ledEndIndex"])
      setGlobalVariable(G_IS_ALBUM_HIGHLIGHTED, "True")
      highlightAlbum(int(getGlobalVariable(G_SELECTED_LED_START_INDEX)), \
                     int(getGlobalVariable(G_SELECTED_LED_END_INDEX)))
      break
    LOG("No match, continuing search...")

  LOG("Album match search finished!")
  return found





######################################################################
#                           FLASK APIS                               #
######################################################################

@app.route("/ledStatus", methods=["GET"])
def ledStatus():
  """
     Return status of LEDs
  """

  LOG("Returning LED Status")
  return jsonify({"message": "Success!", "ledStatus": G_LED_STATUS}), 200

######################################################################

@app.route("/albumWall", methods=['GET', 'POST'])
def albumWall():
  """
     Main handler for album wall control
  """

  data = request.get_json()

  LOG("Retrieved data:")
  LOG(data)

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

  LOG(f'Album currently highlighted = {getGlobalVariable(G_IS_ALBUM_HIGHLIGHTED)}')
  if getGlobalVariable(G_IS_ALBUM_HIGHLIGHTED) == "True":
    LOG(f'Currently selected artist = {getGlobalVariable(G_SELECTED_ARTIST)}')
    LOG(f'Currently selected album = {getGlobalVariable(G_SELECTED_ALBUM)}')

  # Argument validity check
  # ledStatus must be one of "on" or "off"
  # Either both or neither of artistName and albumName should be set
  if (artistName is None and albumName is not None) or \
     (artistName is not None and albumName is None) or \
     (ledStatus != "on" and ledStatus != "off"):
    abort(400)
  
  # Turn off LEDs. Tautulli considers a track change as playback stop event, so ensure that nothing is playing before turning off. Without this check, the LEDs power cycle between every track
  if ledStatus == "off" and artistName is None and albumName is None:
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

    albumFound = findPossibleAlbumMatch(artistName, albumName)

    if not albumFound:
      ret = turnOn()

  LOG("Request processed successfully!")
  return jsonify({"message": "Success!"}), 200





######################################################################

if __name__ == "__main__":
  # Remove existing DB if present
  try:
    os.remove(app.config["DATABASE"])
  except OSError as e:
    pass

  # Initialize empty DB
  with app.app_context():
    initDb()

  # Start flask app
  app.run(host="0.0.0.0", port=80)
