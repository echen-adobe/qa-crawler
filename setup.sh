sudo apt-get update
sudo apt-get install -y python3-venv
cd qa-crawler
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
playwright install