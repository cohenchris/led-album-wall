from flask import Flask, request, jsonify
#fron rpi_ws281x import PixelStrip, Color

app = Flask(__name__)

SUCCESS = {"message": "LED update succeeded!"}

CHECK_ABORT = lambda ret: abort(500) if not ret else None

# LED strip configuration:
LED_COUNT = 30          # Number of LED pixels.
LED_PIN = 18            # GPIO pin connected to the data line.
LED_FREQ_HZ = 800000    # LED signal frequency in hertz (usually 800kHz)
LED_DMA = 10            # DMA channel to use for generating signal.
LED_BRIGHTNESS = 255    # Set to 0 for darkest and 255 for brightest.
LED_INVERT = False      # True to invert the signal (when using NPN transistor level shift).
LED_WIPE_INTERVAL = 50  # When wiping all LEDs, this is the delay between wiping each pixel (in ms)

# Initialize LED strips
#strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
#strip.begin()

NUM_ALBUMS = 8
G_LED_STATUS = "off"


def colorWipe(color, reverse=False):
  """
     Wipe color across LEDs, one light at a time.
  """
  start, end, step = (strip.numPixels() - 1, -1, -1) if reverse else (0, strip.numPixels, 1)
  
  for i in range(start, end, step):
    #strip.setPixelColor(i, color)
    #strip.show()
    time.sleep(LED_WIPE_INTERVAL / 1000.0)


def turnOn():
  """
     Turn on the LEDs in ambient RGB mode.
  """
  ret = False

  # Wipe white across the strip
  ret = colorWipe(Color(255, 255, 255))

  if ret:
    LED_STATUS = "on"
    # Turn on RGB Ambient mode
    ret = ledAmbientRgb()

  return ret


def turnOff():
  """
     Turn off LEDs in reverse.
  """
  ret = False

  ret = colorWipe(Color(0, 0, 0), reverse=True)

  if ret:
    LED_STATUS = "off"

  return ret


def loadAlbumConfig():
  """
     Load the albums.ini config file, which should contain 8 albums. This function should return an array
     of dictionaries, where each dictionary represents the config data
  """
  ret = False

  config = configparser.ConfigParser()
  config.read("albums.ini")

  albums = []

  for i in range(NUM_ALBUMS):
    albumDict = {}
    keyName = f'Album{i}'

    albumDict["albumName"] = config.get(keyName, "albumName")
    albumDict["artistName"] = config.get(keyName, "artistName")
    albums.append(albumDict)

  print(albums)

  ret = True
  
  return albums, ret


def highlightAlbum(ledStartIndex, ledEndIndex):
  """
     Highlight the album at provided index. We should iterate through every LED, turning off LEDs that are
     not under the given albumIndex, and turning on LEDs that are under the given albumIndex
  """
  ret = False

  ret = ledStartIndex is not None and ledEndIndex is not None

  if ret:
    for i in range(strip.numPixels()):
      if ledStartIndex <= i <= ledEndIndex:
        # If LED is within range of album to light up, turn it to white
        strip.setPixelColor(i, Color(255, 255, 255))
      else:
        # If LED is NOT within range, turn it off
        strip.setPixelColor(i, Color(0, 0, 0))
      
      strip.show()
      time.sleep(LED_WIPE_INTERVAL / 1000.0)

  return ret


def findPossibleAlbumMatch(artistName, albumName):
  """
     Given an artistName and albumName, search the wall for a match.
  """
  found = False
  ret = False
  
  # Check validity of parameters
  ret = artistName is not None and albumName is not None
  
  if ret:
    # This loads the provided albums.ini file, and returns them in an array of dictionaries
    wallAlbums, ret = loadAlbumConfig()
  
    if ret:
      # Search for a match within albums on the wall
      for album in wallAlbums:
          # If there is a match, highlight the album on the wall
          if album["artistName"] == artistName and album["albumName"] == albumName:
              found = True
              ret = highlightAlbum(album["ledStartIndex"], album["ledEndIndex"])

  return found, ret


@app.route("/wall", methods=['POST'])
def wall():
  """
     Main handler for album wall control
  """
  ret = False

  data = request.get_json()
  
  # Update the LED strips based on the provided data
  
  # If the provided status is "off", turn LEDs off, then quit
  led_status = data.get("led_status")
  
  # Turn off LEDs
  if led_status == "off" and led_status != G_LED_STATUS:
    ret = turnOff()
  
  # Turn on LEDs
  elif led_status == "on":
    # First, we should determine if there's a match. If there is, then we should highlight that album.
    # The idea is that, if the lights are off, we don't want to turn them all on, THEN highlight the album.
    # If there's a match, we should highlight the album. If not, we should execute the normal turnOn function.

    # Parse artist/album data
    artistName = data.get("artistName")
    albumName = data.get("albumName")

    albumFound, ret = findPossibleAlbumMatch(artistName, albumName)
    CHECK(ret)

    if not albumFound:
      ret = turnOn()
      CHECK(ret)

    ret = True
  
  # Return response from the API, depending on the value of "ret"
  True if ret else abort(500)

if __name__ == "__main__":
    app.run()
