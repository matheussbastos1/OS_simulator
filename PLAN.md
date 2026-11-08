# ROADMAP DE DESENVOLVIMENTO E CONTROLE DE EXECUÇÃO — OS SIMULATOR

> **Diretriz de Controle:** Este plano de execução reflete o ciclo de vida incremental do projeto **OS Simulator**. Nenhum item de checklist deve ser marcado como concluído antecipadamente. A marcação ocorre única e exclusivamente após a implementação, teste automatizado, validação contra o `tests/GROUND_TRUTH.md` e consolidação na branch correspondente.

---

## ESTRATÉGIA DE BRANCHES E FLUXO DE TRABALHO

- `main`: Branch de produção / versões consolidadas e estáveis.
- `dev`: Branch principal de desenvolvimento e integração contínua (Branch padrão de trabalho).
- Branches de funcionalidade (Features e Fixes):
  - `feature/fase-0-documentacao`: Governança, especificação arquitetural e contratos (Fase 0).
  - `fix/fase-0-consistencia`: Revisão documental, portas de desacoplamento e alinhamento pré-implementação (Fase 0.1).
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
- [x] Realizar push da branch `feature/fase-0-documentacao` para `origin`.
- [x] Integrar a branch `feature/fase-0-documentacao` à branch `dev`.
- [x] Realizar push da branch `dev` para `origin`.

---

### Fase 0.1 — Auditoria de Consistência, Desacoplamento e Pré-Implementação
**Branch:** `fix/fase-0-consistencia`  
**Objetivo:** Estabelecer as portas abstratas `BlockDevicePort` e `AuthorizationPort` com adaptadores provisórios (`InMemoryBlockDevice`, `BootstrapSecurityPolicy`), alinhar comandos da CLI com a sintaxe oficial do professor, refinar PBKDF2 (600k iterações) e AES-256-GCM, distinguir as 3 origens de páginas no fluxo de Page Fault / Swap e consolidar casos de teste no Ground Truth.

- [x] Criar e alternar para a branch `fix/fase-0-consistencia` a partir de `dev`.
- [x] Especificar o contrato formal de armazenamento `BlockDevicePort` e o adaptador provisório `InMemoryBlockDevice`.
- [x] Especificar o contrato formal de segurança `AuthorizationPort` e o adaptador provisório `BootstrapSecurityPolicy`.
- [x] Atualizar os diagramas Mermaid na arquitetura para evidenciar a evolução dos adaptadores entre as Etapas 1, 2, 3 e 4.
- [x] Alinhar integralmente os comandos da CLI com a sintaxe oficial (`--size`, `--details`, `--name`, `--type`, `--user`, `--key`).
- [x] Atualizar a especificação de credenciais para PBKDF2-HMAC-SHA256 com 600.000 iterações e salt de 16 bytes.
- [x] Especificar criptografia em repouso AES-256-GCM com nonce exclusivo de 12 bytes, tag de autenticação e separação de chaves.
- [x] Corrigir o tratamento de Page Fault para diferenciar origens (Imagem de Processo, Zero-Fill sob Demanda, Slot de Swap).
- [x] Preservar tanto o cenário `MEM-004A` (tradução página 1 -> moldura 12) quanto `MEM-004B` (página 1, moldura 5 -> endereço 20484).
- [x] Revisar o cenário determinístico `MEM-005` (Swap e Page Fault sem falso swap-in de páginas não descarregadas).
- [x] Remover badges de licença no `README.md` até definição formal pelo proprietário.
- [x] Executar auditoria cruzada de consistência entre todos os documentos revisados.
- [x] Registrar commits no padrão Conventional Commits na branch `fix/fase-0-consistencia`.
- [x] Realizar push da branch `fix/fase-0-consistencia` para `origin`.
- [x] Integrar as alterações à branch `dev`.
- [x] Realizar push da branch `dev` para `origin`.

---

### Fase 1 — Subsistema de Sistema de Arquivos
**Branch:** `feature/etapa-1-filesystem`  
**Objetivo:** Construir a camada de representação em árvore de arquivos e diretórios, VFS, abstração de i-nodes e blocos de dados, suportando três estratégias de alocação de armazenamento e diagnóstico de fragmentação, operando sobre `BlockDevicePort` e `AuthorizationPort`.

- [x] Definir a hierarquia de nós (`Node`, `DirectoryNode`, `FileNode`) e resolução de caminhos VFS (absolutos e relativos).
- [x] Implementar a abstração de i-nodes (`Inode`) com metadados POSIX simulados (tamanho, permissões, proprietário, timestamps, blocos).
- [x] Implementar a porta `BlockDevicePort` e o adaptador provisório em memória `InMemoryBlockDevice`.
- [x] Implementar a porta `AuthorizationPort` e a política provisória `BootstrapSecurityPolicy`.
- [x] Implementar a Estratégia de Alocação Contígua com First-Fit / Best-Fit e detecção de fragmentação externa.
- [x] Implementar a Estratégia de Alocação Encadeada (FAT — File Allocation Table) com encadeamento de ponteiros.
- [x] Implementar a Estratégia de Alocação Indexada com bloco de índices direto e indireto.
- [x] Implementar cálculo matemático preciso de fragmentação interna (último bloco) e fragmentação externa.
- [x] Implementar os comandos da CLI: `mkdir`, `create --size`, `ls`, `cd`, `write_file`, `read_file`, `fs_status --details`.
- [x] Implementar suite de testes unitários para o sistema de arquivos.
- [x] Validar e homologar os cenários determinísticos `FS-001`, `FS-002` e `FS-003` do `tests/GROUND_TRUTH.md`.
- [x] Consolidar commits e integrar à `dev`.

---

### Fase 1.1 — Correções Técnicas Pós-Auditoria (Sistema de Arquivos)
**Branch:** `fix/etapa-1-auditoria`  
**Objetivo:** Eliminar as três ressalvas técnicas identificadas na auditoria de 08/11/2026: atomicidade de gravação com rollback em disco cheio, desacoplamento rigoroso entre alocação lógica e dispositivo de blocos, e diferenciação visual precisa no mapa de blocos (`[I]` vs `[D]`).

- [x] Criar e alternar para a branch `fix/etapa-1-auditoria` a partir de `dev`.
- [x] Implementar atomicidade e rollback em `write_data` contra falhas de espaço em disco nas 3 estratégias.
- [x] Garantir reaproveitamento seguro de blocos em disco quase cheio (in-place expansion / delta allocation).
- [x] Desacoplar estratégias de alocação de detalhes internos de `DiskBlock` e `InMemoryBlockDevice` (eliminação total de `hasattr`).
- [x] Adicionar primitivas padronizadas `is_block_free` e `allocate_specific_blocks` à porta `BlockDevicePort`.
- [x] Atualizar mapa de blocos em `fs_status --details` para distinguir `[I]` (índice), `[D]` (dados), `[.]` (livre) e `[X]` (danificado).
- [x] Implementar suite de testes de regressão e validação (`tests/test_audit_fixes.py`).
- [x] Validar cenário determinístico `FS-004` (transacionalidade de gravação) no Ground Truth.
- [x] Atualizar documentação arquitetural e especificações de algoritmos.

---

### Fase 2 — Entrada e Saída (I/O), Escalonamento e RAID
**Branch:** `feature/etapa-2-io-raid`  
**Objetivo:** Construir a camada de gerenciamento de requisições de E/S (`IORequest`), algoritmos de escalonamento de braço de disco magnético, simulação de SSD com Wear Leveling e arranjos redundantes de discos (RAID 0, 1, 4 e 5), substituindo o adaptador `InMemoryBlockDevice` pelo `IOManager` via `BlockDevicePort`.

- [x] Integrar operações de leitura e escrita do `FileSystemService` ao subsistema de `IOManager` via `BlockDevicePort`.
- [x] Implementar a abstração `IORequest` com atributos de bloco alvo, trilha, tipo (leitura/escrita) e prioridade (`Incremento 1`).
- [x] Implementar fila de requisições `IOQueue` e a classe base `DiskScheduler` (`Incremento 1`).
- [x] Implementar o algoritmo de escalonamento FCFS (First-Come, First-Served) (`Incremento 2`).
- [x] Implementar o algoritmo de escalonamento SSTF (Shortest Seek Time First) com cálculo de deslocamento total de trilhas e desempate determinístico (`Incremento 2`).
- [x] Implementar o algoritmo de escalonamento SCAN (Elevator) (`Incremento 2`).
- [x] Implementar o algoritmo de escalonamento C-SCAN (Circular SCAN) com retorno sem atendimento (`Incremento 2`).
- [x] Implementar a simulação de SSD (`SSDDevice`), blocos físicos (`SSDBlock`), camada FTL e algoritmos de *Wear Leveling* dinâmico e estático (`Incremento 3`).
- [x] Implementar a abstração `PhysicalDisk` em memória, simulando múltiplos discos independentes, trilhas, setores e posse de `DiskBlock` (`Incremento 4`).
- [x] Implementar arranjo RAID 0 (Striping puro) (`Incremento 4`).
- [x] Implementar arranjo RAID 1 (Mirroring puro com espelhamento transparente) (`Incremento 4`).
- [x] Implementar arranjo RAID 4 (Striping com disco de paridade dedicado) (`Incremento 4`).
- [x] Implementar arranjo RAID 5 (Striping com paridade distribuída rotativa esquerda-simétrica) (`Incremento 4`).
- [x] Implementar o cálculo de paridade XOR byte a byte entre blocos (`Incremento 4`).
- [x] Implementar mecanismo de injeção de falha física em disco (`fail()`) e algoritmo de reconstrução *on-the-fly* e regeneração (`rebuild_disk`) (`Incremento 4`).
- [x] Implementar o adaptador `IOBlockDeviceAdapter` conectando o `FileSystemService` ao `IOManager` e arranjos RAID (`Incremento 5`).
- [x] Implementar comandos interativos na CLI (`io_status`, `io_scheduler`, `io_benchmark`, `ssd_status`, `raid_status`, `raid_fail`, `raid_rebuild`, `raid_init`) (`Incremento 6`).
- [x] Validar e homologar os cenários determinísticos `IO-001` (SSTF 208 trilhas) e `IO-002` (RAID 5 XOR) do `tests/GROUND_TRUTH.md` (`Incremento 7`).
- [x] Consolidar commits incrementais via Conventional Commits e preparar branch para validação (`Incremento 7`).

---

### Fase 3 — Segurança, Controle de Acesso e Proteção
**Branch:** `feature/etapa-3-security`  
**Objetivo:** Construir o subsistema de controle de segurança substituindo `BootstrapSecurityPolicy` pelo `SecurityManager` via `AuthorizationPort`, com PBKDF2-HMAC-SHA256 (600k iterações), controle de acesso por ACLs e permissões POSIX, anéis de privilégio (Usuário vs. Kernel), auditoria, criptografia AES-256-GCM em repouso e antivírus simulado.

- [ ] Implementar as entidades `User` e `Group`, gerenciando identidades e associações múltiplas.
- [ ] Implementar o serviço de autenticação com derivação de chave criptográfica via PBKDF2-HMAC-SHA256 (600.000 iterações) e salts de 16 bytes (`secrets.token_bytes`).
- [ ] Implementar o modelo de anéis de execução: Modo Usuário (Ring 3) e Modo Kernel (Ring 0).
- [ ] Implementar a classe `ACL` com validação de permissões `rwx` para Proprietário, Grupo e Outros, com conversão octal (`0o755`, `0o750`, `0o644`, etc.).
- [ ] Substituir o adaptador provisório de segurança por `SecurityManager` na porta `AuthorizationPort`.
- [ ] Implementar o subsistema de Auditoria (`AuditLog`), registrando acessos concedidos, negados, logins e operações privilegiadas.
- [ ] Implementar criptografia AES-256-GCM com nonce exclusivo de 12 bytes, tag de autenticação e separação de chaves.
- [ ] Implementar o verificador de integridade via hash SHA-256 de blocos e HMAC do Kernel para prevenir adulterações coordenadas.
- [ ] Implementar o motor de antivírus simulado (`antivirus_scan`) baseado em assinaturas simuladas.
- [ ] Implementar os comandos da CLI: `login --user`, `chmod`, `encrypt_file --key`, `antivirus_scan`.
- [ ] Validar e homologar os cenários determinísticos `SEC-001`, `SEC-002` e `SEC-003` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

### Fase 4 — Gerenciamento de Memória Real e Virtual
**Branch:** `feature/etapa-4-memory`  
**Objetivo:** Construir o subsistema de gerenciamento de memória dividido em Área Reservada Contígua e Área Dinâmica Paginada (MMU, Page Tables, molduras, Page Fault com origens válidas, políticas LRU e Segunda Chance, e Swap integrado via `BlockDevicePort`).

- [ ] Implementar a abstração de Memória Física (`PhysicalMemory`) dividida em Área Reservada e Área Dinâmica.
- [ ] Implementar o gerenciador da Área Reservada Contígua com alocação First-Fit / Best-Fit de `MemorySegment`.
- [ ] Implementar o cálculo de fragmentação externa na Área Reservada e o algoritmo de desfragmentação / compactação (`memory_compact --reserved`).
- [ ] Implementar a infraestrutura de Memória Paginada: `PageTable`, `PageTableEntry` (bits: present, dirty, referenced, last_access, e `page_origin`) e molduras físicas (`Frame`).
- [ ] Implementar o componente `MMU` para tradução de endereços lógicos em físicos: $(p, d) \to (f, d)$.
- [ ] Implementar o tratamento de `PageFaultException` distinguindo origens: Imagem de Processo, Zero-Fill-on-Demand e Swap.
- [ ] Implementar descarte de página vítima limpa (`dirty == False`) e swap-out de página modificada (`dirty == True`).
- [ ] Implementar a política de substituição de páginas LRU (Least Recently Used) baseada em idade/timestamp de acesso.
- [ ] Implementar a política de substituição Segunda Chance (Clock Algorithm) baseada no bit de referência.
- [ ] Implementar a partição de `SwapManager` integrada ao armazenamento secundário simulado via `BlockDevicePort`.
- [ ] Implementar cálculo de fragmentação interna na última página lógica do processo.
- [ ] Implementar a integração completa com o ciclo de vida de processos (`create_process --name --size --type`, `terminate_process --name`, `execute_step --process --instruction`).
- [ ] Validar e homologar os cenários determinísticos `MEM-001`, `MEM-002`, `MEM-003`, `MEM-004A`, `MEM-004B` e `MEM-005` do `tests/GROUND_TRUTH.md`.
- [ ] Consolidar commits e integrar à `dev`.

---

## CONTROLE DE VERSÕES E RELEASES

| Versão | Fase | Descrição | Status |
|---|---|---|---|
| `v0.1.0` | Fase 0 | Fundação Arquitetural, Governança Git e Especificações | Concluído |
| `v0.1.1` | Fase 0.1 | Revisão de Consistência, Portas/Adaptadores e Alinhamento CLI | Concluído |
| `v0.2.0` | Fase 1 | Sistema de Arquivos VFS, i-nodes e Alocação via Adaptador em Memória | Concluído |
| `v0.3.0` | Fase 2 | E/S, Escalonamento de Disco e Arranjos RAID | Concluído (Pronto para Homologação) |
| `v0.4.0` | Fase 3 | Segurança, Autenticação, ACLs e Criptografia AES-256-GCM | Não iniciado |
| `v1.0.0` | Fase 4 | Gerenciamento de Memória, Paginação, Swap e Integração Global | Não iniciado |
