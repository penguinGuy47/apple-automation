"""Fake apple.com for rehearsing the bot end to end without touching Apple.

    python tests/mock_apple.py 8765
    python bot.py -c tests/mock_config.toml watch --now

Pickup flips to "available" on the 3rd availability check, and the checkout
pages mimic Apple's pickup flow (security code is 123).
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer
from urllib.parse import urlparse, parse_qs
calls = {"n": 0}
PAGES = {
 "/product": '<script>fetch("/shop/fulfillment-messages?pl=true&parts.0=MQZ93LL%2FA&location=60201")</script><h1>iPhone Duo</h1><button onclick="location=\'/shop/bag\'">Add to Bag</button>',
 "/shop/bag": '<button data-autom="checkout" onclick="location=\'/shop/checkout\'">Check Out</button>',
 "/shop/checkout": '''<button onclick="document.getElementById('p').style.display='block'">I'll pick it up</button>
   <div id="p" style="display:none"><input aria-label="ZIP Code" name="location">
   <label><input type="radio" name="s"> Old Orchard</label><label><input type="radio" name="s"> Woodfield</label>
   <select name="timeslot"><option value="">Choose</option><option value="9-915">9:00</option></select>
   <button data-autom="continue-button-label" onclick="location='/shop/checkout/pickup'">Continue to Pickup Details</button></div>''',
 "/shop/checkout/pickup": '<button data-autom="continue-button-label" onclick="location=\'/shop/checkout/payment\'">Continue to Payment</button>',
 "/shop/checkout/payment": '<input aria-label="Security Code" name="securityCode"><button data-autom="continue-button-label" onclick="if(document.querySelector(\'input\').value===\'123\')location=\'/shop/checkout/review\'">Review Your Order</button>',
 "/shop/checkout/review": '<button data-autom="continue-button-label" onclick="location=\'/shop/checkout/thankyou\'">Place Your Order</button>',
 "/shop/checkout/thankyou": '<h1>Thank you for your order.</h1>',
}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/shop/fulfillment-messages":
            calls["n"] += 1
            part = parse_qs(u.query)["parts.0"][0]
            disp = "available" if calls["n"] >= 3 else "unavailable"
            body = {"body":{"content":{"pickupMessage":{"stores":[{"storeName":"Woodfield","storeNumber":"R100","city":"Schaumburg","partsAvailability":{part:{"pickupDisplay":disp,"pickupSearchQuote":"Today"}}}]}}}}
            b = json.dumps(body).encode(); ct = "application/json"
        elif u.path in PAGES:
            b = f"<html><body>{PAGES[u.path]}</body></html>".encode(); ct = "text/html"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(b)
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
