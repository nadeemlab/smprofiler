from requests import get as requests_get
from requests import post as requests_post

from smprofiler.db.exchange_data_formats.findings import FindingCreate

def test_findings():
    response = requests_get('http://smprofiler-apiserver-testing-apiserver:8080/findings/?study=Melanoma+intralesional+IL2')
    if response.status_code != 200:
        raise ValueError(f'Get request not OK. HTTP {response.status_code} {response.reason}')
    items = response.json()
    if tuple(items) != ():
        raise ValueError(f'Expected no findings. Got: {items}')
    finding = FindingCreate(
        study='Melanoma intralesional IL2',
        email='test@example.com',
        url='http://example.com/finding-route',
        description='Finding statement.',
        background='Notes.',
        p_value=0.5,
        effect_size=2.0,
        id_token='token',
    )
    finding_dict = finding.model_dump()
    h = {'Content-Type': 'application/json'}
    response = requests_post('http://smprofiler-apiserver-testing-apiserver:8080/findings/', json=finding_dict, headers=h)
    if response.status_code != 200:
        print(finding_dict)
        print(response.text)
        raise ValueError(f'Post request not OK. HTTP {response.status_code} {response.reason}')
    response = requests_get('http://smprofiler-apiserver-testing-apiserver:8080/findings/?study=Melanoma+intralesional+IL2')
    if response.status_code != 200:
        raise ValueError(f'Get request not OK. HTTP {response.status_code} {response.reason}')
    items = response.json()
    if len(items) != 1:
        raise ValueError(f'Expected one finding just inserted now. Got: {items}')
    item = items[0]
    for attribute in ['study', 'email', 'url', 'description', 'background', 'p_value', 'effect_size']:
        a1 = getattr(finding, attribute)
        a2 = item[attribute]
        if a1 != a2:
            raise ValueError(f'{attribute} value does not agree: {a1} ; {a2}')

if __name__=='__main__':
    test_findings()
