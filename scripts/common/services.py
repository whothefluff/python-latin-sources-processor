import os

#: Where Morpheus and the macronizer listen: localhost, unless SERVICES_HOST names another host
SERVICES_HOST = os.environ.get('SERVICES_HOST', 'localhost')
MORPHEUS_URL = f'http://{SERVICES_HOST}:1500/analysis/word'
MACRONIZER_URL = f'http://{SERVICES_HOST}:8001/macronize-text'
