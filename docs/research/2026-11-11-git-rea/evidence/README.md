# Evidências REA

Os `.json.gz` contêm a saída JSON integral do CLI, comprimida sem alterar o conteúdo. `summary.json` registra SHA-256 do JSON descomprimido, Evidence IDs, parâmetros, cobertura, estatísticas e limitações. `gitlens-timeout.json.gz` é uma falha parcial preservada, não um resultado completo.

Comandos usados (REA 6.7.0, Node 24.22.1):

```bash
rea analyze-javascript-application /usr/share/code/resources/app/extensions/git --source-path package.json --source-path dist/main.js --analysis-timeout-ms 45000 --max-semantic-nodes 10000 --max-semantic-unknowns 10000 --format json
rea analyze-javascript-application /home/vi/.vscode/extensions/eamodio.gitlens-19.5.0 --source-path package.json --source-path dist/gitlens.js --analysis-timeout-ms 45000 --max-semantic-nodes 10000 --max-semantic-unknowns 10000 --format json
rea analyze-javascript-application /home/vi/.vscode/extensions/eamodio.gitlens-19.5.0 --source-path package.json --source-path dist/gitlens.js --analysis-timeout-ms 120000 --max-semantic-nodes 3000 --max-semantic-unknowns 3000 --format json
```

Para reproduzir, é necessário preservar os pacotes das versões analisadas. Uma atualização da instalação muda a identidade do artefato. As evidências são estáticas e parciais; não representam benchmark, captura de interação ou prova de execução dos caminhos.

Verificação de integridade dos arquivos entregues:

```python
import gzip, hashlib, json
from pathlib import Path

root = Path('docs/research/2026-11-11-git-rea/evidence')
for item in json.loads((root / 'summary.json').read_text()):
    raw = gzip.decompress((root / item['file']).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == item['json_sha256']
    result = json.loads(raw)
    evidence = result.get('details', {}).get('partial_observation', result)
    assert evidence['evidence_id'] == item['evidence_id']
```
