<?php
// BUKA PHP Proxy — forwards all requests to Flask app on port 5000
$uri = $_SERVER['REQUEST_URI'];
$target = 'http://127.0.0.1:5000' . $uri;
$method = $_SERVER['REQUEST_METHOD'];

$ch = curl_init($target);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);

$req_headers = [];
foreach (getallheaders() as $k => $v) {
    if (strtolower($k) === 'host') continue;
    $req_headers[] = "$k: $v";
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $req_headers);

if ($method === 'POST') {
    $body = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
}

$raw = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$header_size = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
curl_close($ch);

if ($raw === false) {
    http_response_code(503);
    echo 'BUKA proxy error';
    exit;
}

// Parse headers and body
$header_str = substr($raw, 0, $header_size);
$body       = substr($raw, $header_size);

http_response_code($code);
foreach (explode("\n", $header_str) as $line) {
    $line = trim($line);
    if (preg_match('/^(Content-Type|Set-Cookie|Location):/i', $line)) {
        header($line, false);
    }
}
echo $body;
