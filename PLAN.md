# ROADMAP DE DESENVOLVIMENTO E CONTROLE DE EXECUÇÃO — OS SIMULATOR

> **Diretriz de Controle:** Este plano de execução reflete o ciclo de vida incremental do projeto **OS Simulator**. Nenhum item de checklist deve ser marcado como concluído antecipadamente. A marcação ocorre única e exclusivamente após a implementação, teste automatizado, validação contra o `tests/GROUND_TRUTH.md` e consolidação na branch correspondente.

---

## ESTRATÉGIA DE BRANCHES E FLUXO DE TRABALHO

- `main`: Branch de produção / versões consolidadas e estáveis.
- `dev`: Branch principal de desenvolvimento e integração contínua.
- Branches de funcionalidade (Features):
  - `feature/fase-0-documentacao`: Governança, especificação arquitetural e contratos (Fase 0).
  - `feature/etapa-1-filesystem`: Subsistema de Arquivos, VFS, i-nodes e estratégias de alocação (Fase 1).
  - `feature/etapa-2-io-raid`: Gerenciamento de E/S, escalonamento de disco e controladores RAID (Fase 2).
  - `feature/etapa-3-security`: Autenticação, controle de acesso ACL, anéis de privilégio e criptografia (Fase 3).
  - `feature/etapa-4-memory`: Memória reservada, paginação virtual, MMU, substituição e Swap (Fase 4).

### Regra de Transição entre Etapas
Cada etapa segue rigorosamente:
1. Criação da branch a partir de `dev`.
2. Implementação restrita ao escopo da etapa.
3. Criação de testes unitários e de integração baseados no `tests/GROUND_TRUTH.md`.
4. Execução e validação de conformidade.
5. Commits descritivos no padrão *Conventional Commits*.
6. Push da branch para o repositório remoto `origin`.
7. Pull Request / Merge para `dev`.
8. Atualização deste `PLAN.md`.
9. Início da etapa seguinte somente com autorização explícita.

---

## CRONOGRAMA DETALHADO DAS FASES

---

### Fase 0 — Base, Governança e Fundação Arquitetural
**Branch:** `feature/fase-0-documentacao`  
**Objetivo:** Estabelecer a fundação documental, governança Git, arquitetura dos quatro subsistemas, estruturas de dados, especificações algorítmicas, contratos da CLI e casos de teste determinísticos (Ground Truth).

- [x] Inspecionar workspace e validar requisitos do ambiente (Windows 11 / Python 3.13 / Git).
- [x] Inicializar o repositório Git local e configurar o controle remoto `origin` (`https://github.com/matheussbastos1/OS_simulator.git`).
- [x] Criar a branch de integração `dev`.
- [x] Criar a branch de trabalho `feature/fase-0-documentacao`.
- [x] Elaborar o documento de governança e regras para agentes (`AGENTS.md`).
- [x] Elaborar o plano detalhado de execução (`PLAN.md`).
- [x] Elaborar a arquitetura completa do sistema com diagramas Mermaid (`docs/ARCHITECTURE.md`).
- [x] Especificar o catálogo completo de estruturas de dados e tipagens (`docs/DATA_STRUCTURES.md`).
- [x] Especificar os contratos e lógicas detalhadas de todos os algoritmos (`docs/ALGORITHMS.md`).
- [x] Especificar o dicionário de comandos e padrões de formatação da CLI (`docs/CLI_AND_OUTPUTS.md`).
- [x] Documentar os cenários determinísticos oficiais de validação (`tests/GROUND_TRUTH.md`).
- [x] Criar o manual principal do projeto e instruções de uso (`README.md`).
- [x] Executar auditoria cruzada de consistência entre todos os documentos.
- [x] Registrar commits no padrão Conventional Commits na branch `feature/fase-0-documentacao`.
- [ ] Realizar push da branch `feature/fase-0-documentacao` para `origin`.
- [ ] Integrar a branch `feature/fase-0-documentacao` à branch `dev`.
- [ ] Realizar push da branch `dev` para `origin`.

---

### Fase 1 — Subsistema de Sistema de Arquivos
**Branch:** `feature/etapa-1-filesystem`  
**Objetivo:** Construir a camada de representação em árvore de arquivos e diretórios, VFS, abstração de i-nodes e blocos de dados, suportando três estratégias de alocação de armazenamento e diagnóstico de fragmentação.

- [ ] Definir a hierarquia de nós (`Node`, `DirectoryNode`, `FileNode`) e resolução de caminhos VFS (absolutos e relativos).
- [ ] Implementar a abstração de i-nodes (`Inode`) com metadados POSIX simulados (tamanho, permissões, proprietário, timestamps, blocos).
- [ ] Implementar a tabela de blocos simulados (`DiskBlock`) na memória.
- [ ] Implementar a Estratégia de Alocação Contígua com First-Fit / Best-Fit e detecção de fragmentação externa.
- [ ] Implementar a Estratégia de Alocação Encadeada (FAT — File Allocation Table) com encadeamento de ponteiros.
- [ ] Implementar a Estratégia de Alocação Indexada com bloco de índices direto e indireto.
- [ ] Implementar cálculo matemático preciso de fragmentação interna (último bloco) e fragmentação externa.
- [ ] Implementar os comandos da CLI: `mkdir`, `create`, `ls`, `cd`, `write_file` (versão base), `read_file` (versão base), `fs_status`.
- [ ] Implementar suite de testes unitários para o sistema de arquivos.
- [ ] Validar e homologar os cenários determinísticos `FS-001`, `FS-002` e `FS-003` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

### Fase 2 — Entrada e Saída (I/O), Escalonamento e RAID
**Branch:** `feature/etapa-2-io-raid`  
**Objetivo:** Construir a camada de gerenciamento de requisições de E/S (`IORequest`), algoritmos de escalonamento de braço de disco magnético, simulação de SSD com Wear Leveling e arranjos redundantes de discos (RAID 0, 1, 4 e 5) com tolerância a falhas.

- [ ] Integrar operações de leitura e escrita do `FileSystemService` ao subsistema de `IOManager`.
- [ ] Implementar a abstração `IORequest` com atributos de bloco alvo, trilha, tipo (leitura/escrita) e prioridade.
- [ ] Implementar fila de requisições e a classe base `DiskScheduler`.
- [ ] Implementar o algoritmo de escalonamento FCFS (First-Come, First-Served).
- [ ] Implementar o algoritmo de escalonamento SSTF (Shortest Seek Time First) com cálculo de deslocamento total de trilhas.
- [ ] Implementar o algoritmo de escalonamento SCAN (Elevator).
- [ ] Implementar o algoritmo de escalonamento C-SCAN (Circular SCAN).
- [ ] Implementar a abstração `SSDController` com matriz de desgaste e algoritmo de *Wear Leveling* dinâmico.
- [ ] Implementar a abstração `PhysicalDisk` em memória, simulando múltiplos discos independentes.
- [ ] Implementar arranjo RAID 0 (Striping puro).
- [ ] Implementar arranjo RAID 1 (Mirroring puro).
- [ ] Implementar arranjo RAID 4 (Striping com disco de paridade dedicado).
- [ ] Implementar arranjo RAID 5 (Striping com paridade distribuída e rotação).
- [ ] Implementar o cálculo de paridade XOR bit a bit / byte a byte entre blocos.
- [ ] Implementar mecanismo de injeção de falha física em disco e algoritmo de reconstrução on-the-fly (`rebuild`).
- [ ] Implementar saídas de diagnóstico de E/S e estado de saúde dos discos na CLI.
- [ ] Validar e homologar os cenários determinísticos `IO-001` e `IO-002` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

### Fase 3 — Segurança, Controle de Acesso e Proteção
**Branch:** `feature/etapa-3-security`  
**Objetivo:** Construir o subsistema de controle de segurança, autenticação robusta, autorização baseada em Listas de Controle de Acesso (ACL) e permissões POSIX, separação estrita de modos de privilégio (Usuário vs. Kernel), logs de auditoria invioláveis, criptografia em repouso e integridade com antivírus simulado.

- [ ] Implementar as entidades `User` e `Group`, gerenciando identidades e associações múltiplas.
- [ ] Implementar o serviço de autenticação com derivação de chave criptográfica via PBKDF2-HMAC-SHA256 e salts pseudoaleatórios criptograficamente seguros (`secrets.token_bytes`).
- [ ] Implementar o modelo de anéis de execução: Modo Usuário (Ring 3) e Modo Kernel (Ring 0), interceptando chamadas privilegiadas.
- [ ] Implementar a classe `ACL` com validação de permissões `rwx` para Proprietário, Grupo e Outros, com conversão bidirecional octal (`0o755`, `0o750`, `0o644`, etc.).
- [ ] Integrar a checagem de ACL em todas as operações de leitura, escrita, execução e criação do VFS.
- [ ] Implementar o subsistema de Auditoria (`AuditLog`), registrando acessos concedidos, acessos negados, autenticações e operações de sistema.
- [ ] Implementar o módulo de criptografia de arquivos em repouso com derivação de chave e marcação em i-node.
- [ ] Implementar o verificador de integridade via hash SHA-256 de blocos, detectando adulteração.
- [ ] Implementar o motor de antivírus simulado (`antivirus_scan`) baseado em base de assinaturas simuladas.
- [ ] Implementar os comandos da CLI: `login`, `whoami`, `chmod`, `useradd`, `groupadd`, `encrypt_file`, `antivirus_scan`.
- [ ] Validar e homologar os cenários determinísticos `SEC-001`, `SEC-002` e `SEC-003` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

### Fase 4 — Gerenciamento de Memória Real e Virtual
**Branch:** `feature/etapa-4-memory`  
**Objetivo:** Construir o subsistema de gerenciamento de memória dividido em Área Reservada Contígua (para Kernel e drivers com diagnóstico de fragmentação externa e compactação dinâmica) e Área Dinâmica Paginada (com MMU, Page Tables, molduras físicas, tratamento de Page Fault, políticas LRU e Segunda Chance, e Swap integrado ao disco simulado).

- [ ] Implementar a abstração de Memória Física (`PhysicalMemory`) dividida em Área Reservada e Área Dinâmica.
- [ ] Implementar o gerenciador da Área Reservada Contígua com alocação First-Fit / Best-Fit de `MemorySegment`.
- [ ] Implementar o cálculo de fragmentação externa na Área Reservada e o algoritmo de desfragmentação / compactação (`memory_compact`).
- [ ] Implementar a infraestrutura de Memória Paginada: `PageTable`, `PageTableEntry` (bits: present, dirty, referenced, last_access) e molduras físicas (`Frame`).
- [ ] Implementar o componente `MMU` para tradução de endereços lógicos em físicos: $(p, d) \to (f, d)$.
- [ ] Implementar a interrupção de falta de página (`PageFaultException`) e seu handler de resolução.
- [ ] Implementar a política de substituição de páginas LRU (Least Recently Used) baseada em idade/timestamp de acesso.
- [ ] Implementar a política de substituição Segunda Chance (Clock Algorithm) baseada no bit de referência.
- [ ] Implementar a partição de `SwapManager` integrada ao subsistema de armazenamento simulado, com suporte a swap-in e swap-out de páginas com bit *dirty*.
- [ ] Implementar cálculo de fragmentação interna na última página lógica do processo.
- [ ] Implementar a integração completa com o ciclo de vida de processos (`create_process`, `terminate_process`, `execute_step`).
- [ ] Implementar os comandos da CLI: `create_process`, `terminate_process`, `memory_status`, `memory_compact`, `translate_address`, `execute_step`.
- [ ] Validar e homologar os cenários determinísticos `MEM-001`, `MEM-002`, `MEM-003`, `MEM-004` e `MEM-005` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

## CONTROLE DE VERSÕES E RELEASES

| Versão | Fase | Descrição | Status |
|---|---|---|---|
| `v0.1.0` | Fase 0 | Fundação Arquitetural, Governança Git e Especificações | Em andamento |
| `v0.2.0` | Fase 1 | Sistema de Arquivos VFS, i-nodes e Alocação | Não iniciado |
| `v0.3.0` | Fase 2 | E/S, Escalonamento de Disco e Arranjos RAID | Não iniciado |
| `v0.4.0` | Fase 3 | Segurança, Autenticação, ACLs e Criptografia | Não iniciado |
| `v1.0.0` | Fase 4 | Gerenciamento de Memória, Paginação, Swap e Integração Global | Não iniciado |
