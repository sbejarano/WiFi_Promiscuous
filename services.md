```mermaid
flowchart TD
    gpsd[gpsd.service + gpsd.socket]
    pps[gps-pps.service]
    gpssvc[gps_service.py]
    gpsjson[gps.json]

    espwd[esp_usb_watchdog.service]
    wificap[wifi-capture.service]
    capjson[/dev/shm/wifi_capture.json]

    trilat[trilateration.service]
    triljson[trilaterated.json]

    apwriter[ap_position_writer.service]
    db[(SQLite DB\n(ap_locations))]

    gpsd --> gpssvc
    pps --> gpssvc
    gpssvc --> gpsjson

    espwd --> wificap
    gpsjson --> wificap
    wificap --> capjson

    capjson --> trilat
    trilat --> triljson

    triljson --> apwriter
    apwriter --> db
```
