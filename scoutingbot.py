import os
import hmac
import hashlib
import math
import requests
import re
import time
import typing
import statistics

from flask import abort, Flask, jsonify, request
from zappa.asynchronous import task

app = Flask(__name__)


"-----------------------------------------"
"-----------------------------------------"
"---- CONSTANT DECLARATION START HERE ----"
"-----------------------------------------"
"-----------------------------------------"

# Dictionary containing the real-life event name and the event ID as stored in the database
EVENT_IDS = {
  'plano': 'txpla',
}

# Standard response payload for when the event is not found
EVENT_NOT_FOUND = {
  'response_type': 'in_channel',
  'text': 'Event not found'
}


# Standard response payload for when the match is not found
MATCH_NOT_FOUND = {
  'response_type': 'in_channel',
  'text': 'Match not found'
}


"-----------------------------------------"
"-----------------------------------------"
"----- COMMANDS AND TASKS START HERE -----"
"-----------------------------------------"
"-----------------------------------------"


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
  """
  List the teams at a particular event
  """
  if not is_request_valid(request):
    abort(400)
    
  text = request.form['text']
  
  event, _ = find_event_and_match(text)
  
  if event == None:
    return EVENT_NOT_FOUND
  
  # This gets all the teams at the event
  teams = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetSingleByTypeAndId/teams/{EVENT_IDS[event]}').json()
  return_str = ''
  for team in teams:
    name = teams[team]['team_name']
    location = teams[team]['team_loc']
    # Append the team name, number, and location to the response string
    return_str += f'\n* {team}-{name} \t{location}'
  
  return jsonify(
    response_type = 'in_channel',
    type='mrkdwn',
    text = return_str
  )
  
  # If there is no event, then event not found
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

  match_data = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match_number:03d}-').json()

  if match_data == None:
    return MATCH_NOT_FOUND
  
  teams = get_match_alliances(event, match_number)
  if teams == None:
    return MATCH_NOT_FOUND

  post_predictions(event, teams, request.form['response_url'])
  
  return jsonify(
    response_type = 'in_channel',
    text = 'predicting'
  )
  
@task
def post_predictions(event: str, teams: dict, response_url: str):
  """
  Post the predictions calculated in slack. This asynchronous task is needed because it takes more than 3 seconds to calculate the statistics.
  """
  red_stats = [get_team_statistics(event, team) for team in teams['red']]
  blue_stats = [get_team_statistics(event, team) for team in teams['blue']]
  
  red_teams = teams['red']
  blue_teams = teams['blue']
  
  red_mean = sum([x[0] for x in red_stats])
  blue_mean = sum([x[0] for x in blue_stats])
  red_confint = 1.96 * math.sqrt(sum([x[1]**2 for x in red_stats]))
  blue_confint = 1.96 * math.sqrt(sum([x[1]**2 for x in blue_stats]))

  requests.post(
    response_url,
    json={
      'response_type': 'in_channel',
      'text': 
        (f'Red Alliance: {red_teams}\'s estimation: {round(red_mean, 2)}±{round(red_confint, 2)}\n'
        f'Blue Alliance: {blue_teams}\'s estimation: {round(blue_mean, 2)}±{round(blue_confint, 2)}')
        
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

  match_data = get_match_data(event, match_number)
  
  if match_data == None:
    return MATCH_NOT_FOUND
  
  teams = get_teams_at_match(event, match_number)
  if teams == None:
    return MATCH_NOT_FOUND
  
  
  return jsonify(
    response_type = 'in_channel',
    text = str([str(x) + '-' + str(get_estimated_score(get_match_data(event, match_data, x))) for x in teams])
  )
  
"-----------------------------------------"
"-----------------------------------------"
"------- HELPER METHODS START HERE -------"
"-----------------------------------------"
"-----------------------------------------"
  
  
def is_request_valid(request: request) -> bool:
  """
  Check that the POST request is actually from Slack using slack's signing secret.
  
  :returns: whether the POST request was actually from slack
  """
  
  key = os.environ.get("SLACK_SIGNING_SECRET")
  basestring = 'v0:' + request.headers['X-Slack-Request-Timestamp'] + ':' + str(request.get_data(), 'utf-8')

  # Hash the basestring using the signing secret as the key in order to get the signature
  signature = 'v0=' + hmac.new(
    bytes(key, 'utf-8'),
    bytes(basestring, 'utf-8'),
    hashlib.sha256
  ).hexdigest()
  slacksig = request.headers['X-Slack-Signature']

  # If the signature is equal to the signature sent by slack, then it is indeed from slack.
  return hmac.compare_digest(slacksig, signature)
  
def find_event_and_match(text: str) -> typing.Tuple[typing.Optional['string'], typing.Optional[int]]:
  """
  Finds the event ID and QM number from the text sent from the command.
  
  :returns: A tuple (event ID, match number) extracted from the text.
  """
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
  """
  Get a list of teams at a match
  
  :returns: A list of team numbers at a match
  """
  
  match_data = get_match_data(event, match)
  if match_data == None:
    return None
  return [int(x.split('-')[1]) for x in match_data]

def get_estimated_score(match_data: dict) -> float:
  """
  Estimate the score contribution of a particular team based on their match data.
  
  :returns: A float estimating the contribution.
  """
  
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
  
  # Gives autonomous points
  for x in auto_high:
    score += (4.3, 4.8)[auto_high[x]] * x
  score += auto_low * 2
  if auto_line: score += 5
  
  # Gives teleop points
  for x in tele_high:
    score += (2.15, 2.4)[tele_high[x]] * x
  score += tele_low
  
  # Gives endgame points
  if climbed: score += 25
  if parked: score += 5
  
  return score

def get_team_statistics(event: str, team: int) -> typing.Tuple[float, float]:
  """
  Get the cumulative mean and standard deviation of a team at a certain event.
  
  :return: A tuple of (mean, standard deviation)
  """
  
  matches = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchDataByTeamAndCompetition/{event}/{team:4}').json()
  estimates = [get_estimated_score(matches[x]) for x in matches]
  mean = statistics.mean(estimates)
  stddev = statistics.stdev(estimates, mean)
  return mean, stddev

def get_match_data(event: str, match: int, team: int = -1):
  """
  Get the match data for a match, or for a specific team at that match.
  """
  
  if team < 0:
    return requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match:03d}-').json()
  else:
    return requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetMatchData/{event}/{match:03d}-').json()[f'{match:03}-{team:4}']
  
def get_match_alliances(event: str, match: int) -> typing.Dict[str, typing.List[int]]:
  """
  Get the alliance partners in a certain match
  
  :returns: dict with keys 'red' and 'blue'.
  """
  match_data = requests.get(f'https://us-central1-pearadox-2020.cloudfunctions.net/GetSingleByTypeAndId/matches/{event}').json()
  
  # Searches for the correct database entry
  match_data = [x for x in filter(lambda l: int(l['match']) == match, match_data.values())][0] 
  
  red = []
  blue = []
  
  # Adds the team numbers of each alliance to their lists
  for num in range(1, 4):
    red.append(int(match_data[f'r{num}']))
    
  for num in range(1, 4):
    blue.append(int(match_data[f'b{num}']))
    
  return {'red': red, 'blue': blue}

def get_team_alliance(event: str, match: int, team: int) -> typing.Optional[str]:
  """
  Get the alliance a team is on in a certain match
  
  :returns: 'red' or 'blue', or None if team is not in the match
  """
  
  if team in get_match_alliances(event, match)['red']:
    return 'red'
  elif team in get_match_alliances(event, match)['blue']:
    return 'blue'
  else:
    return None