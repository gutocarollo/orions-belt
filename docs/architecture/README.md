# Arquitetura do Orion's Belt

Esta coleção contém a arquitetura canônica atual e alvo do framework. Ela responde **como os
subsistemas se relacionam e quais contratos devem existir**; o manual continua sendo a fonte para
uso e configuração de cada componente, e `docs/planning/` permanece arquivo histórico das decisões.

## Documentos

| Documento | Status | Função |
|---|---|---|
| [Arquitetura-alvo](arquitetura-alvo.md) | active | Estado atual versus alvo, três grafos, ingestão segura, confiança, evals, release gate e sequência de adoção. |

## Precedência

Em conflito, vale esta ordem:

1. código, schemas executáveis e testes;
2. esta arquitetura para contratos e direção técnica;
3. `docs/manual/` para comportamento instalado e operação atual;
4. `docs/planning/` como registro histórico.

Uma capacidade só muda de **planejada** para **implementada** quando código, teste e documentação do
manual concordam. Um diagrama alvo não é prova de implementação.
