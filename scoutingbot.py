import os
import asyncio
import hmac
import hashlib
import requests
import re
import time
import typing
import statistics

from flask import abort, Flask, jsonify, request
from zappa.asynchronous import task

app = Flask(__name__)

EVENT_IDS = {
  'plano': 'txpla',
}

EVENT_NOT_FOUND = {
  'response_type': 'in_channel',
  'text': 'Event not found'
}

MATCH_NOT_FOUND = {
  'response_type': 'in_channel',
  'text': 'Match not found'
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
  
  print(signature)
  print(slacksig)
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
  
  return EVENT_NOT_FOUND
  
@app.route('/commands/predictmatch', methods=['POST'])
def predictmatch():
  if not is_request_valid(request):
    abort(400)
    
  text = request.form['text']
    
  event, match_number = find_event_and_match(text)
  
  if event == None:
    return EVENT_NOT_FOUND
  if match_number == None:
    return MATCH_NOT_FOUND

  print(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match_number:03d}-')
  match_data = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match_number:03d}-').json()
  print(type(match_data))
  
  if match_data == None:
    return MATCH_NOT_FOUND
  
  teams = get_teams_at_match(event, match_number)
  if teams == None:
    return MATCH_NOT_FOUND
  
  post_predictions(event, teams, request.form['response_url'])
  
  return jsonify(
    response_type = 'in_channel',
    text = 'predicting'
  )
  
@task
def post_predictions(event: str, teams: list, response_url: str):
  requests.post(
    response_url,
    json={
      'response_type': 'in_channel',
      'text': str([get_team_statistics(event, x) for x in teams])
    }
  )
      
@app.route('/commands/estimatematch', methods=['POST'])
def estimatematch():
  if not is_request_valid(request):
    abort(400)
    
  text = request.form['text']
    
  event, match_number = find_event_and_match(text)
  
  if event == None:
    return EVENT_NOT_FOUND
  if match_number == None:
    return MATCH_NOT_FOUND

  print(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match_number:03d}-')
  match_data = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match_number:03d}-').json()
  
  if match_data == None:
    return MATCH_NOT_FOUND
  
  teams = get_teams_at_match(event, match_number)
  if teams == None:
    return MATCH_NOT_FOUND
  
  return jsonify(
    response_type = 'in_channel',
    text = str([str(x) + '-' + str(get_estimated_score(match_data[f'{match_number:03}-{x:4}'])) for x in teams])
  )
  
def find_event_and_match(text: str) -> typing.Tuple[typing.Optional['string'], typing.Optional[int]]:
  for event in EVENT_IDS:
    if event in text.lower():
      numbers = re.findall(r'\d+', text)
      match_number = 0
      if len(numbers) == 1:
        match_number = numbers[0]
        return (EVENT_IDS[event], int(match_number))
      if len(numbers) == 2:
        match_number = numbers[0] * 10 + numbers[1]
        return (EVENT_IDS[event], int(match_number))
      else:
        return (EVENT_IDS[event], None)
  return (None, None)

def get_teams_at_match(event: str, match: int) -> typing.Optional[typing.List[int]]:
  match_data = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match:03d}-').json()
  if match_data == None:
    return None
  return [int(x.split('-')[1]) for x in match_data]

def get_estimated_score(match_data: dict) -> float:
  auto_high = {match_data['auto_HighClose']: match_data['auto_conInnerClose'],
               match_data['auto_HighFrontCP']: match_data['auto_conInnerFrontCP'],
               match_data['auto_HighLine']: match_data['auto_conInnerLine']
  }
  auto_low = match_data['auto_Low']
  auto_line = match_data['auto_leftSectorLine']
  
  tele_high = {match_data['tele_HighClose']: match_data['tele_conInnerClose'],
               match_data['tele_HighFrontCP']: match_data['tele_conInnerFrontCP'],
               match_data['tele_HighLine']: match_data['tele_conInnerLine'],
               match_data['tele_HighBackCP']: match_data['tele_conInnerBackCP']
  }
  tele_low = match_data['tele_Low']
  climbed = match_data['tele_Climbed']
  parked = match_data['tele_UnderSG']
  
  score = 0
  
  for x in auto_high:
    score += (4.3, 4.8)[auto_high[x]] * x
  score += auto_low * 2
  if auto_line: score += 5
  
  for x in tele_high:
    score += (2.15, 2.4)[tele_high[x]] * x
  score += tele_low
  if climbed: score += 25
  if parked: score += 5
  
  return score

def get_team_statistics(event: str, team: int) -> typing.Tuple[float, float]:
  matches = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchDataByTeamAndCompetition/{event}/{team:4}').json()
  estimates = [get_estimated_score(matches[x]) for x in matches]
  mean = statistics.mean(estimates)
  stddev = statistics.stdev(estimates, mean)
  return mean, stddev