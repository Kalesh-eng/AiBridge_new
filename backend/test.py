import difflib
key = 'accidenthistory'
actual_key = 'accidents'
score = difflib.SequenceMatcher(None, key, actual_key).ratio()
print(f'Score: {score:.3f}')
print(f'Threshold: 0.55')
print(f'Match: {score >= 0.55}')