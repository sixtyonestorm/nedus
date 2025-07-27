import os
import json
import logging
import subprocess
import threading
import time
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from typing import Dict, List, Any, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "albion-market-flipper-secret-key")

# Global data storage
offers_data = []
requests_data = []
items_lookup = {}
worlds_lookup = {}
cart_items = []
profit_log = []

# Quality mapping
QUALITY_MAP = {
    1: "Normal",
    2: "Good", 
    3: "Outstanding",
    4: "Excellent",
    5: "Masterpiece"
}

# Constants
SAVE_INTERVAL = 50
MIN_PROFIT_SILVER = 1000
MIN_ROI_PERCENTAGE = 10.0

class AlbionDataSniffer:
    """Handles real-time data from albiondata-client.exe"""
    def __init__(self, executable_path: str = "./client/albiondata-client.exe"):
        self.executable_path = executable_path
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.read_thread: Optional[threading.Thread] = None
        self.current_city = ""
        self.current_player_name = ""
        self.current_location_id = None
        self.connection_established = False
        self.current_operation = None
        self.items_since_last_save = 0

    def start(self) -> None:
        """Start the albiondata-client process"""
        if self.running:
            return
        logging.info("🔌 Starting Albion Data Client...")
        try:
            if not os.path.exists(self.executable_path):
                logging.warning(f"❌ Albion Data Client not found at {self.executable_path}")
                logging.info("ℹ️  Please place albiondata-client.exe in the ./client/ directory")
                return

            # Linux subprocess configuration
            self.process = subprocess.Popen(
                [
                    self.executable_path,
                    "-debug",
                    "-events", "0",
                    "-operations", "75,76",
                    "-ignore-decode-errors"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            self.running = True
            self.read_thread = threading.Thread(target=self._read_output, daemon=True)
            self.read_thread.start()
            logging.info("✅ Albion Data Client started successfully")
            logging.info("ℹ️  Please change location in-game to establish connection")
        except Exception as e:
            logging.error(f"❌ Failed to start Albion Data Client: {e}")

    def _read_output(self) -> None:
        """Read and process output from albiondata-client"""
        try:
            if not self.process or not self.process.stdout:
                return
            while self.running:
                try:
                    line = self.process.stdout.readline()
                    if line:
                        self._process_line(line.strip())
                    else:
                        if self.process.poll() is not None:
                            break
                        time.sleep(0.1)
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logging.error(f"Error reading line: {e}")
                    continue
        except Exception as e:
            logging.error(f"❌ Error reading client output: {e}")

    def _process_line(self, line: str) -> None:
        """Process a single line of output from the client"""
        try:
            # Detect operation type
            if 'opAuctionGetOffers' in line or '[75]' in line:
                self.current_operation = 'offers'
                logging.debug("🔄 Switched to processing offers")
            elif 'opAuctionGetRequests' in line or '[76]' in line:
                self.current_operation = 'requests'
                logging.debug("🔄 Switched to processing requests")

            # Parse player name
            player_match = re.search(r'Updating player to (.+)\.', line)
            if player_match:
                new_name = player_match.group(1)
                if self.current_player_name != new_name:
                    self.current_player_name = new_name
                    if not self.connection_established:
                        logging.info(f"✅ Player connection established: {new_name}")
                        self.connection_established = True

            # Parse location ID
            location_match = re.search(r'Updating player location to (\d+)\.', line)
            if location_match:
                location_id = int(location_match.group(1))
                self.current_location_id = location_id
                new_city = worlds_lookup.get(str(location_id), f"Unknown Location ({location_id})")
                if self.current_city != new_city:
                    self.current_city = new_city
                    logging.info(f"📍 Location changed: {self.current_city}")
                    self.connection_established = True

            # Extract and process JSON data
            json_objects = re.findall(r'\{.*?\}', line)
            for json_str in json_objects:
                try:
                    obj = json.loads(json_str)
                    self._process_market_data(obj, self.current_operation)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logging.error(f"❌ Error processing line: {e}")

    def _process_market_data(self, data: Dict[str, Any], operation_type: Optional[str] = None) -> None:
        """Process market data objects from the client"""
        global offers_data, requests_data
        try:
            # Ensure required keys are present
            required_keys = {"Id", "ItemTypeId", "UnitPriceSilver", "Amount", "QualityLevel"}
            if not required_keys.issubset(data.keys()):
                logging.debug(f"Skipping data due to missing keys: {data}")
                return

            # Data cleaning and standardization
            order_id = data["Id"]
            raw_item_id = data["ItemTypeId"]
            unit_price_silver = int(data["UnitPriceSilver"])
            amount = int(data["Amount"])

            # Quality level validation
            raw_quality = data.get("QualityLevel", 1)
            try:
                quality_level = int(raw_quality)
                if quality_level < 1:
                    quality_level = 1
                elif quality_level > 5:
                    quality_level = 5
            except (ValueError, TypeError):
                quality_level = 1

            # Extract enchantment
            item_id = raw_item_id
            enchant = 0
            if "@" in raw_item_id:
                base_name, enchant_str = raw_item_id.split("@", 1)
                try:
                    enchant = int(enchant_str)
                    item_id = base_name
                except ValueError:
                    pass
            if enchant == 0 and "EnchantmentLevel" in data:
                enchant = int(data.get("EnchantmentLevel", 0))

            location_id = self.current_location_id if self.current_location_id is not None else -1

            # Create standardized order object
            order = {
                "id": order_id,
                "item_id": item_id,
                "item_name": items_lookup.get(item_id, {}).get('display_name', item_id),
                "enchant": enchant,
                "quality_level": quality_level,
                "amount": amount,
                "unit_price_silver": unit_price_silver,
                "location_id": location_id,
                "timestamp": datetime.now().isoformat()
            }

            # Deduplication and update logic - handle None operation_type
            if operation_type == 'offers':
                target_list = offers_data
            elif operation_type == 'requests':
                target_list = requests_data
            else:
                return  # Skip if operation type is not recognized

            existing_order_index = next((i for i, o in enumerate(target_list) if o['id'] == order_id), None)

            if existing_order_index is not None:
                target_list[existing_order_index] = order
                action_msg = "🔁 Updated"
            else:
                target_list.append(order)
                action_msg = "📦 Added"
                self.items_since_last_save += 1

            logging.debug(f"{action_msg} {operation_type[:-1] if operation_type else 'order'}: {order['item_name']} (ID: {order_id}, Quality: {order['quality_level']}) - Total {operation_type}: {len(target_list)}")

            # Periodic saving
            if self.items_since_last_save >= SAVE_INTERVAL:
                self.items_since_last_save = 0
                if operation_type == 'offers':
                    save_offers_data()
                elif operation_type == 'requests':
                    save_requests_data()

        except Exception as e:
            logging.error(f"❌ Error processing market data: {e}")

    def stop(self) -> None:
        """Stop the albiondata-client process"""
        if not self.running:
            return
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                logging.info("🔌 Albion Data Client stopped")
            except Exception as e:
                logging.error(f"❌ Error stopping client: {e}")
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=5)

def load_data():
    """Load items and worlds data from JSON files"""
    global items_lookup, worlds_lookup
    
    # Load items data
    try:
        with open('data/items.json', 'r', encoding='utf-8') as f:
            items_data = json.load(f)
            for item in items_data:
                items_lookup[item['unique_name']] = {
                    'id': item['id'],
                    'display_name': item['display_name'],
                    'enchant': item.get('enchant', 0)
                }
        logging.info(f"✅ Loaded {len(items_lookup)} items from items.json")
    except FileNotFoundError:
        logging.warning("❌ items.json not found. Item names will not be resolved.")
    except Exception as e:
        logging.error(f"❌ Error loading items.json: {e}")

    # Load worlds data
    try:
        with open('data/worlds.json', 'r', encoding='utf-8') as f:
            worlds_lookup = json.load(f)
        logging.info(f"✅ Loaded {len(worlds_lookup)} locations from worlds.json")
    except FileNotFoundError:
        logging.warning("❌ worlds.json not found. Location names will not be resolved.")
    except Exception as e:
        logging.error(f"❌ Error loading worlds.json: {e}")

def save_offers_data():
    """Save offers data to JSON file"""
    try:
        os.makedirs('data', exist_ok=True)
        with open('data/offers.json', 'w', encoding='utf-8') as f:
            json.dump(offers_data, f, indent=2, ensure_ascii=False)
        logging.debug(f"💾 Saved {len(offers_data)} offers to data/offers.json")
    except Exception as e:
        logging.error(f"❌ Error saving offers data: {e}")

def save_requests_data():
    """Save requests data to JSON file"""
    try:
        os.makedirs('data', exist_ok=True)
        with open('data/requests.json', 'w', encoding='utf-8') as f:
            json.dump(requests_data, f, indent=2, ensure_ascii=False)
        logging.debug(f"💾 Saved {len(requests_data)} requests to data/requests.json")
    except Exception as e:
        logging.error(f"❌ Error saving requests data: {e}")

def calculate_arbitrage_opportunities(min_profit_silver=1000, min_roi_percentage=10.0):
    """Calculate profitable arbitrage opportunities"""
    opportunities = []
    
    for offer in offers_data:
        # Find matching requests for the same item
        matching_requests = [
            req for req in requests_data
            if req['item_id'] == offer['item_id'] 
            and req['enchant'] == offer['enchant']
            and req['quality_level'] == offer['quality_level']
            and req['location_id'] != offer['location_id']  # Different locations
        ]
        
        for request in matching_requests:
            # Calculate profit
            buy_price = offer['unit_price_silver']
            sell_price = request['unit_price_silver']
            profit_per_unit = sell_price - buy_price
            
            if profit_per_unit > min_profit_silver:
                roi_percentage = (profit_per_unit / buy_price) * 100
                
                if roi_percentage >= min_roi_percentage:
                    max_quantity = min(offer['amount'], request['amount'])
                    total_profit = profit_per_unit * max_quantity
                    
                    opportunity = {
                        'item_id': offer['item_id'],
                        'item_name': offer['item_name'],
                        'enchant': offer['enchant'],
                        'quality_level': offer['quality_level'],
                        'quality_name': QUALITY_MAP.get(offer['quality_level'], 'Unknown'),
                        'buy_location': worlds_lookup.get(str(offer['location_id']), f"Location {offer['location_id']}"),
                        'sell_location': worlds_lookup.get(str(request['location_id']), f"Location {request['location_id']}"),
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'profit_per_unit': profit_per_unit,
                        'roi_percentage': roi_percentage,
                        'max_quantity': max_quantity,
                        'total_profit': total_profit,
                        'offer_id': offer['id'],
                        'request_id': request['id']
                    }
                    opportunities.append(opportunity)
    
    # Sort by total profit descending
    opportunities.sort(key=lambda x: x['total_profit'], reverse=True)
    return opportunities

# Global sniffer instance and data initialization
sniffer = AlbionDataSniffer()
load_data()

@app.route('/')
def index():
    """Main dashboard"""
    status = {
        'connection_established': sniffer.connection_established,
        'current_player': sniffer.current_player_name,
        'current_location': sniffer.current_city,
        'offers_count': len(offers_data),
        'requests_count': len(requests_data),
        'sniffer_running': sniffer.running
    }
    return render_template('index.html', status=status)

@app.route('/arbitrage')
def arbitrage():
    """Arbitrage opportunities page"""
    min_profit = request.args.get('min_profit', 1000, type=int)
    min_roi = request.args.get('min_roi', 10.0, type=float)
    
    opportunities = calculate_arbitrage_opportunities(min_profit, min_roi)
    
    return render_template('arbitrage.html', 
                         opportunities=opportunities, 
                         min_profit=min_profit, 
                         min_roi=min_roi)

@app.route('/cart')
def cart():
    """Shopping cart page"""
    total_investment = sum(item.get('total_cost', 0) for item in cart_items)
    total_potential_profit = sum(item.get('total_profit', 0) for item in cart_items)
    
    return render_template('cart.html', 
                         cart_items=cart_items,
                         total_investment=total_investment,
                         total_potential_profit=total_potential_profit)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    """Add item to cart"""
    offer_id = request.form.get('offer_id')
    request_id = request.form.get('request_id')
    quantity = int(request.form.get('quantity', 1))
    
    # Find the corresponding opportunity
    opportunities = calculate_arbitrage_opportunities()
    opportunity = next((opp for opp in opportunities 
                       if opp['offer_id'] == offer_id and opp['request_id'] == request_id), None)
    
    if opportunity:
        cart_item = {
            'id': f"{offer_id}_{request_id}",
            'item_name': opportunity['item_name'],
            'enchant': opportunity['enchant'],
            'quality_name': opportunity['quality_name'],
            'buy_location': opportunity['buy_location'],
            'sell_location': opportunity['sell_location'],
            'buy_price': opportunity['buy_price'],
            'sell_price': opportunity['sell_price'],
            'quantity': quantity,
            'total_cost': opportunity['buy_price'] * quantity,
            'total_profit': opportunity['profit_per_unit'] * quantity,
            'roi_percentage': opportunity['roi_percentage']
        }
        
        # Check if item already in cart
        existing_item = next((item for item in cart_items if item['id'] == cart_item['id']), None)
        if existing_item:
            existing_item['quantity'] += quantity
            existing_item['total_cost'] = existing_item['buy_price'] * existing_item['quantity']
            existing_item['total_profit'] = (existing_item['sell_price'] - existing_item['buy_price']) * existing_item['quantity']
        else:
            cart_items.append(cart_item)
        
        flash(f"Added {quantity}x {opportunity['item_name']} to cart", "success")
    else:
        flash("Item not found", "error")
    
    return redirect(url_for('arbitrage'))

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    """Remove item from cart"""
    item_id = request.form.get('item_id')
    global cart_items
    cart_items = [item for item in cart_items if item['id'] != item_id]
    flash("Item removed from cart", "info")
    return redirect(url_for('cart'))

@app.route('/analytics')
def analytics():
    """Analytics and profit tracking page"""
    return render_template('analytics.html', profit_log=profit_log)

@app.route('/start_sniffer', methods=['POST'])
def start_sniffer():
    """Start the data sniffer"""
    sniffer.start()
    flash("Data sniffer started", "success")
    return redirect(url_for('index'))

@app.route('/stop_sniffer', methods=['POST'])
def stop_sniffer():
    """Stop the data sniffer"""
    sniffer.stop()
    flash("Data sniffer stopped", "info")
    return redirect(url_for('index'))

@app.route('/api/status')
def api_status():
    """API endpoint for status updates"""
    return jsonify({
        'connection_established': sniffer.connection_established,
        'current_player': sniffer.current_player_name,
        'current_location': sniffer.current_city,
        'offers_count': len(offers_data),
        'requests_count': len(requests_data),
        'sniffer_running': sniffer.running
    })

if __name__ == '__main__':
    # Load initial data
    load_data()
    
    # Start sniffer automatically if executable exists
    if os.path.exists("./client/albiondata-client.exe"):
        sniffer.start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
