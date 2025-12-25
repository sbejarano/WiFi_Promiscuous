<?php
// --------------------------------------------------
// UI capture control (START / STOP)
// --------------------------------------------------

$state_file = "/media/sbejarano/Developer1/wifi_promiscuous/tmp/capture.state";

if (!isset($_GET['cmd'])) {
    http_response_code(400);
    echo "Missing cmd";
    exit;
}

$cmd = $_GET['cmd'];

if ($cmd === "start") {
    file_put_contents($state_file, "START");
    echo "CAPTURE STARTED";
}
elseif ($cmd === "stop") {
    file_put_contents($state_file, "STOP");
    echo "CAPTURE STOPPED";
}
elseif ($cmd === "status") {
    if (file_exists($state_file)) {
        echo trim(file_get_contents($state_file));
    } else {
        echo "STOP";
    }
}
else {
    http_response_code(400);
    echo "Invalid cmd";
}
