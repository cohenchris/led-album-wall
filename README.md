# Dynamic LED Album Display

This project is written for an ARM-based Raspberry Pi, which controls a WS2812B individually-addressable LED strip.

## Requirements
- ARM-based Raspberry Pi
- Individually-addressable LED strip (I used a WS2812B model)

**TODO:**
- Photo of albums on wall
- Photo of LED strips
- Photo of Raspberry Pi hooked up


## Basic Functionality
### Endpoint
When this flask endpoint is started, it will listen at `ip.of.pi:80/albumWall`.

### Expected Format
The API expects a JSON payload. The following fields are valid, and will be handled:
```json
{
  "ledStatus"  : "ledStatusHere",
  "artistName" : "artistNameHere",
  "albumName"  : "albumNameHere"
}
```

For the given input to be valid:
- `ledStatus` must be present for each call, and should either be set to `"on"` or `"off"`
- `artistName` and `albumName` must either both be present, or both be absent.

If either of these conditions are not met, the API will respond with a `400 Bad Request` HTTP Response Code.

### Logic Behavior
The following diagram illustrates the behavior of this API:
![Logic Flowchart](./DynamicAlbumWall.png)


## Deployment
This file can be deployed in a variety of ways. This is intended to run on your local network without internet connection, so I'm ignoring the warnings about using a production WSGI server. Personally, I just created a systemd service to run the flask app with python3:

1. Create a Systemd Service File:
```service
[Unit]
Description=Dynamic LED Album Wall
After=network.target

[Service]
User=root
ExecStart=/usr/bin/python3 /home/pi/dynamic-led-album-wall/albumWall.py

[Install]
WantedBy=multi-user.target
```

Place this service file into `/etc/systemd/system` directory. I named the file `albumwall.service`.

Execute `chmod 644 albumwall.service` for correct file permissions.

2. Reload Systemd and Start the Service
```bash
sudo systemctl daemon-reload
sudo systemctl start albumwall.service
sudo systemctl enable albumwall.service
```

3. Check the Service Status
```bash
sudo systemctl status albumwall.service
```

The output of this command should show something along these lines:
```bash
● albumwall.service - Dynamic LED Album Wall
    Loaded: loaded (/etc/systemd/system/albumwall.service; enabled; vendor preset: enabled)
    Active: active (running) since Sat 2024-01-13 17:02:13 PST; 2s ago
  Main PID: 807 (python3)
    Tasks: 1 (limit: 414)
      CPU: 1.836s
    CGroup: /system.slice/albumwall.service
            └─807 /usr/bin/python3 /home/pi/dynamic-led-album-wall/albumWall.py

Jan 13 17:02:13 albumwall systemd[1]: Started Dynamic LED Album Wall.
```
