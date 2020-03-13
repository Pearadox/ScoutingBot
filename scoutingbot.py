import os
import hmac
import hashlib
import requests

from flask import abort, Flask, jsonify, request

app = Flask(__name__)

EVENT_IDS = {
  'plano': 'txpla',
}


def is_request_valid(request: request) -> bool:
  key = os.environ.get("SLACK_SIGNING_SECRET")
  basestring = 'v0:' + request.headers['X-Slack-Request-Timestamp'] + ':' + str(request.get_data(), 'utf-8')

  signature = 'v0=' + hmac.new(
    bytes(key, 'utf-8'),
    bytes(basestring, 'utf-8'),
    hashlib.sha256
  ).hexdigest()
  slacksig = request.headers['X-Slack-Signature']
  
  return hmac.compare_digest(slacksig, signature)

@app.route('/commands/scoutinghelp', methods=['POST'])
def scoutinghelp():
  if not is_request_valid(request):
    abort(400)
  
  return jsonify(
    response_type='in_channel',
    text='testing'
  )
  
@app.route('/commands/teamsatevent', methods=['POST'])
def teamsatevent():
  if not is_request_valid(request):
    abort(400)
    
  text = request.form['text']
  
  for event in EVENT_IDS:
    if event in text.lower():
      teams = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetSingleByTypeAndId/teams/{EVENT_IDS[event]}').json()
      return_str = str()
      for team in teams:
        name = teams[team]['team_name']
        location = teams[team]['team_loc']
        
        return_str += f'\n* {team}-{name} \t{location}'
      
      return jsonify(
        response_type = 'in_channel',
        type='mrkdwn',
        text = return_str
      )
  
  return jsonify(
    response_type = 'in_channel',
    text = 'Event not found'
  )