# ESPECIFICAÇÃO DE ALGORITMOS E CONTRATOS LÓGICOS — OS SIMULATOR

> **Status:** Especificação Oficial (Fase 0)  
> **Objetivo:** Estabelecer a especificação matemática, formal e algorítmica de todas as operações computacionais do simulador em suas quatro etapas.

---

## 1. SUBSISTEMA DE SISTEMA DE ARQUIVOS (ETAPA 1)

### 1.1. Alocação Contígua
- **Objetivo:** Alocar um conjunto de blocos fisicamente adjacentes para armazenar um arquivo.
- **Entradas:** `file_size: int` (bytes), `block_size: int` (bytes), `disk_blocks: List[DiskBlock]`.
- **Saídas:** `allocated_block_ids: List[int]` ou exceção de espaço contíguo insuficiente.
- **Pré-condições:** O sistema de arquivos deve possuir pelo menos um bloco livre.
- **Pós-condições:** Os blocos contíguos são marcados como ocupados e atribuídos ao i-node.
- **Passo a Passo:**
  1. Calcular o número de blocos necessários: $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Varrer o array de blocos localizando sequências de blocos com `status == FREE`.
  3. Aplicar a política de seleção:
     - *First-Fit:* Seleciona o primeiro intervalo de tamanho $\ge N$.
     - *Best-Fit:* Seleciona o menor intervalo livre de tamanho $\ge N$.
  4. Se nenhum intervalo contíguo satisfizer $N$, lançar `DiskFragmentationException` (fragmentação externa).
  5. Marcar os $N$ blocos selecionados como `ALLOCATED` e associá-los ao `Inode`.
- **Complexidade:** $O(M)$ onde $M$ é o total de blocos do disco.
- **Casos Extremos:** Disco com espaço total livre suficiente, mas disperso em blocos isolados (gera fragmentação externa); arquivo com tamanho 0 (aloca 0 blocos).
- **Critério de Validação:** Se um arquivo de 3 blocos for solicitado em blocos `[0:Livre, 1:Ocupado, 2:Livre, 3:Livre, 4:Livre]`, deve alocar os blocos `[2, 3, 4]`.

---

### 1.2. Alocação Encadeada (FAT — File Allocation Table)
- **Objetivo:** Alocar blocos arbitrários não adjacentes interligados por ponteiros mantidos em uma tabela FAT centralizada.
- **Entradas:** `file_size: int`, `block_size: int`, `fat_table: Dict[int, Optional[int]]`.
- **Saídas:** `first_block_id: int` e atualização da `fat_table`.
- **Pré-condições:** Quantidade de blocos livres totais $\ge N$.
- **Pós-condições:** Cada bloco aponta para o próximo no arquivo; o último aponta para `EOF` (`-1` ou `None`).
- **Passo a Passo:**
  1. Calcular $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Coletar os primeiros $N$ blocos livres da tabela FAT.
  3. Para $i$ de $0$ até $N-2$, definir `fat_table[blocks[i]] = blocks[i+1]`.
  4. Definir `fat_table[blocks[N-1]] = EOF`.
  5. Gravar `first_block_id = blocks[0]` no `Inode`.
- **Complexidade:** Alocação $O(N)$; leitura do k-ésimo bloco requer navegação encadeada $O(k)$.
- **Casos Extremos:** Não sofre de fragmentação externa; quebra de integridade na cadeia se um ponteiro apontar para bloco fora do intervalo.
- **Critério de Validação:** A leitura sequencial percorre exatamente a lista de blocos na ordem de encadeamento.

---

### 1.3. Alocação Indexada (i-node com Bloco de Índices)
- **Objetivo:** Manter todos os ponteiros de blocos de um arquivo centralizados em um bloco de índices (ou diretamente no vetor de blocos do i-node).
- **Entradas:** `file_size: int`, `block_size: int`, tabela de blocos livres.
- **Saídas:** `index_block_id: int`, `allocated_data_blocks: List[int]`.
- **Pré-condições:** Existência de blocos livres para dados mais o bloco de índice.
- **Pós-condições:** O bloco de índice armazena o vetor ordenado de blocos de dados.
- **Passo a Passo:**
  1. Calcular $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Alocar 1 bloco para índice (`index_block_id`).
  3. Alocar $N$ blocos de dados em posições livres quaisquer.
  4. Gravar os $N$ identificadores no array do bloco de índices.
  5. Registrar o `index_block_id` no `Inode`.
- **Complexidade:** Acesso direto a qualquer bloco lógico em $O(1)$ através da consulta ao índice.
- **Casos Extremos:** Arquivos muito pequenos pagam a sobrecarga de 1 bloco inteiro de índice; arquivos gigantes requerem blocos indiretos.
- **Critério de Validação:** Acesso aleatório ao bloco $k$ não necessita percorrer os blocos anteriores.

---

### 1.4. Métricas de Fragmentação de Armazenamento
- **Fragmentação Interna ($FI$):**
  $$FI = (N \times \text{block\_size}) - \text{file\_size}$$
  Onde $N = \lceil \text{file\_size} / \text{block\_size} \rceil$. Ocorre dentro do último bloco alocado ao arquivo.
- **Fragmentação Externa ($FE$):**
  Espaço total livre no disco que não pode ser aproveitado para uma alocação contígua de tamanho $K$:
  $$FE = \sum \text{tamanho de todos os blocos livres} \quad (\text{se nenhum segmento contíguo} \ge K)$$

---

## 2. SUBSISTEMA DE ENTRADA E SAÍDA (I/O) E ARMAZENAMENTO (ETAPA 2)

### 2.1. Escalonamento FCFS (First-Come, First-Served)
- **Objetivo:** Atender as requisições de E/S na estrita ordem cronológica de chegada à fila.
- **Passo a Passo:**
  1. Manter a fila de requisições como uma FIFO (`collections.deque`).
  2. Para cada requisição $R_i$ com trilha alvo $T_i$:
     - Calcular o deslocamento: $\Delta = |T_i - \text{cabeçote\_atual}|$.
     - Somar $\Delta$ ao `total_head_movement`.
     - Atualizar $\text{cabeçote\_atual} = T_i$.
     - Processar a requisição e remover da fila.

---

### 2.2. Escalonamento SSTF (Shortest Seek Time First)
- **Objetivo:** Atender a requisição da fila que possui a menor distância da posição atual do cabeçote.
- **Entradas:** `initial_head: int`, `queue: List[int]`.
- **Saídas:** Ordem de atendimento e `total_head_movement: int`.
- **Passo a Passo:**
  1. Definir $\text{current\_head} = \text{initial\_head}$ e $\text{total\_movement} = 0$.
  2. Enquanto a fila não estiver vazia:
     - Localizar na fila a requisição $R^*$ que minimiza $|\text{track}(R^*) - \text{current\_head}|$.
     - Se houver empate, escolher a de menor índice ou que mantenha a direção anterior.
     - Calcular $\text{deslocamento} = |\text{track}(R^*) - \text{current\_head}|$.
     - $\text{total\_movement} += \text{deslocamento}$.
     - $\text{current\_head} = \text{track}(R^*)$.
     - Remover $R^*$ da fila.
- **Validação com Cenário Oficial IO-001:**
  - Posição inicial: 53. Fila: `[98, 183, 37, 122, 14]`.
  - Ordem percorrida: $53 \to 37 \to 14 \to 98 \to 122 \to 183$.
  - Movimentos: $|53-37|=16$, $|37-14|=23$, $|14-98|=84$, $|98-122|=24$, $|122-183|=61$.
  - Movimentação total: $16 + 23 + 84 + 24 + 61 = 208$ trilhas.

---

### 2.3. Escalonamento SCAN (Elevador)
- **Objetivo:** Mover o cabeçote em uma direção contínua atendendo requisições até a extremidade do disco (trilha 0 ou trilha máxima), inverter a direção e continuar atendendo.
- **Passo a Passo:**
  1. Ordenar as requisições em duas listas: menores que o cabeçote e maiores que o cabeçote.
  2. Na direção ascendente (`UP`): atender requisições maiores em ordem crescente até o limite do disco (ex.: trilha 199), inverter para `DOWN`, e atender as menores em ordem decrescente.

---

### 2.4. Escalonamento C-SCAN (Circular SCAN)
- **Objetivo:** Fornecer tempo de espera mais uniforme movendo o cabeçote sempre em uma direção; ao atingir o final, retorna imediatamente à extremidade oposta sem atender requisições no retorno.
- **Passo a Passo:**
  1. Na direção ascendente: atende de `current_head` até a trilha final.
  2. Salta imediatamente para a trilha 0 (contabilizando o movimento de retorno conforme a política de métrica configurada).
  3. Continua subindo da trilha 0 até atender as requisições restantes.

---

### 2.5. SSD e Wear Leveling
- **Objetivo:** Uniformizar a contagem de ciclos de escrita entre blocos de memória flash, evitando o desgaste prematuro de células.
- **Passo a Passo:**
  1. Manter uma matriz `write_count: Dict[int, int]` para cada bloco físico do SSD.
  2. Ao gravar um novo bloco, o controlador busca entre os blocos livres aquele com o menor `write_count`.
  3. Incrementar `write_count[block_id] += 1`.
  4. Quando a diferença entre o bloco mais gravado e o menos gravado ultrapassar um limiar (*wear threshold*, ex.: 50 ciclos), acionar o *Wear Leveling Estático*: trocar dados estáticos (frios) de blocos pouco gravados para blocos desgastados, liberando os blocos pouco usados para gravações dinâmicas.

---

### 2.6. Controladores RAID e Tolerância a Falhas

#### A. RAID 0 (Striping)
- Dados divididos em pedaços (*stripes*) intercalados entre $N$ discos.
- Bloco lógico $B$ mapeia para Disco $D = B \pmod N$, Bloco físico $P = \lfloor B / N \rfloor$.
- Nenhuma redundância ($0\%$ de tolerância a falhas).

#### B. RAID 1 (Mirroring)
- Dados gravados identicamente no Disco Primário e no Disco Espelho.
- Capacidade útil: $50\%$ do total. Tolerância: sobrevive à falha de 1 disco em cada par espelhado.

#### C. RAID 4 (Paridade Dedicada)
- $N-1$ discos para dados e 1 disco dedicado exclusivamente para paridade XOR:
  $$P_i = D_{0,i} \oplus D_{1,i} \oplus \dots \oplus D_{N-2,i}$$
- Gargalo de gravação no disco de paridade.

#### D. RAID 5 (Paridade Distribuída)
- Dados e paridades distribuídos rotativamente entre todos os $N$ discos.
- Para uma faixa $S$:
  - Disco da Paridade: $P_{\text{disk}} = (N - 1) - (S \pmod N)$ ou rotação circular padrão.
  - Demais discos na faixa armazenam os blocos de dados.
- **Cálculo de Paridade XOR:**
  Para blocos de $K$ bytes, a paridade é calculada byte a byte:
  $$\text{Parity}[j] = \text{Data}_1[j] \oplus \text{Data}_2[j] \oplus \dots \oplus \text{Data}_{N-1}[j]$$
- **Reconstrução após Falha (Rebuild):**
  Se o Disco $k$ falhar, qualquer bloco ausente $D_k$ é recuperado operando o XOR de todos os blocos sobreviventes da faixa com o bloco de paridade:
  $$D_k[j] = P[j] \oplus \bigoplus_{m \neq k} D_m[j]$$
- **Validação com Cenário Oficial IO-002:**
  - 3 discos, arquivo de 8 KB com blocos de 4 KB (2 blocos de dados + 1 bloco de paridade).
  - Disco 1: Dados 1; Disco 2: Dados 2; Disco 3: Paridade XOR.
  - Falha no Disco 2 $\to$ Dados 2 reconstruídos via `Dados 1 ^ Paridade`.

---

## 3. SUBSISTEMA DE SEGURANÇA E PROTEÇÃO (ETAPA 3)

### 3.1. Autenticação e Derivação de Chave
- **Algoritmo:** PBKDF2 (Password-Based Key Derivation Function 2) com HMAC-SHA256.
- **Passo a Passo:**
  1. Ao registrar usuário:
     - Gerar salt criptográfico aleatório: $\text{salt} = \text{secrets.token\_bytes}(16)$.
     - Derivar hash: $\text{hash} = \text{hashlib.pbkdf2\_hmac}(\text{'sha256'}, \text{password.encode()}, \text{salt}, 100000)$.
     - Armazenar `(username, salt, hash)`.
  2. Ao autenticar:
     - Recuperar `salt` e `hash` armazenados do usuário.
     - Derivar novo hash com a senha fornecida: $\text{test\_hash} = \text{pbkdf2\_hmac}(\dots)$.
     - Comparar utilizando tempo constante: $\text{hmac.compare\_digest}(\text{test\_hash}, \text{stored\_hash})$.
- **Vantagem:** Resistente a ataques de dicionário, rainbow tables e timing attacks.

---

### 3.2. Avaliação de Permissões POSIX e ACL
- **Entradas:** `user: User`, `inode: Inode`, `operation: AccessType` (`READ`, `WRITE`, `EXECUTE`).
- **Passo a Passo:**
  1. Se `user.user_id == 0` (root/Modo Kernel): Acesso irrestrito concedido.
  2. Se `user.username == inode.owner`:
     - Testar os bits de `owner_permissions` contra a operação requerida.
     - Se permitido, retornar `CONCEDIDO`; se negado, retornar `NEGADO`.
  3. Se `inode.group` estiver na lista `user.groups`:
     - Testar os bits de `group_permissions`.
     - Se permitido, retornar `CONCEDIDO`; se negado, retornar `NEGADO`.
  4. Caso contrário:
     - Testar os bits de `others_permissions`.
     - Retornar o resultado do teste.
- **Conversão Octal:** Exemplo `750` $\implies$ Dono: $7$ (`111` binário = `rwx`), Grupo: $5$ (`101` binário = `r-x`), Outros: $0$ (`000` binário = `---`).

---

### 3.3. Criptografia em Repouso
- **Objetivo:** Garantir sigilo dos blocos gravados no disco simulado.
- **Mecanismo:** Cifragem da carga útil do bloco antes da entrega ao `IOManager`.
- **Passo a Passo:**
  1. Na gravação de arquivo com flag de criptografia:
     - O serviço de segurança obtém a chave de cifra derivada da sessão do usuário.
     - O payload do bloco é cifrado gerando `ciphertext`.
     - O bloco de disco físico recebe o `ciphertext`.
  2. Na leitura:
     - O subsistema de I/O lê o bloco cru.
     - O serviço de segurança valida as credenciais do leitor e descriptografa o conteúdo antes de devolvê-lo ao VFS/CLI.

---

### 3.4. Verificação de Integridade e Antivírus Simulado
- **Integridade:**
  - Cada `DiskBlock` calcula $\text{hash} = \text{SHA-256}(\text{data})$.
  - Se o hash calculado divergir do hash registrado no i-node/metadados, sinaliza corrupção física ou adulteração não autorizada.
- **Antivírus Simulado (`antivirus_scan`):**
  - O motor percorre todos os arquivos do sistema e compara assinaturas (padrões de bytes simulados como `"EICAR_SIMULATED_VIRUS_SIG"`) contra o conteúdo de cada bloco.
  - Emite relatório com arquivos limpos, arquivos comprometidos e integridade dos hashes.

---

## 4. SUBSISTEMA DE GERENCIAMENTO DE MEMÓRIA (ETAPA 4)

### 4.1. Alocação na Área Reservada Contígua e Compactação
- **Algoritmo de Alocação:** First-Fit ou Best-Fit sobre a lista ligada de `MemorySegment`.
- **Diagnóstico de Fragmentação Externa:**
  $$\text{Fragmentação Externa} = \text{Espaço Livre Total} - \text{Tamanho do Maior Segmento Livre Contíguo}$$
- **Algoritmo `memory_compact` (Compactação Deslizante):**
  1. Identificar todos os segmentos alocados (`status == ALLOCATED`).
  2. Deslocar os segmentos alocados para a base contígua da memória (endereços iniciais contíguos a partir do fim do Kernel base).
  3. Atualizar os endereços `start_address` e `end_address` de cada processo realocado.
  4. Consolidar todo o espaço livre remanescente em um único grande bloco livre no final da área reservada.

---

### 4.2. Tradução de Endereços Virtuais pela MMU
- **Entradas:** `virtual_address: int`, `page_size: int` (padrão 4096), `page_table: PageTable`.
- **Saídas:** `physical_address: int` ou `PageFaultException`.
- **Passo a Passo:**
  1. Obter o número da página: $p = \lfloor \text{virtual\_address} / \text{page\_size} \rfloor$.
  2. Obter o deslocamento (offset): $d = \text{virtual\_address} \pmod{\text{page\_size}}$.
  3. Consultar a entrada $PTE = \text{page\_table.entries}[p]$.
  4. Se $PTE.\text{present} == \text{False}$:
     - Lançar `PageFaultException(pid, p)`.
  5. Se $PTE.\text{present} == \text{True}$:
     - Atualizar metadados: $PTE.\text{referenced} = \text{True}$, $PTE.\text{last\_access} = \text{time.time}()$.
     - Obter o número da moldura $f = PTE.\text{frame\_id}$.
     - Calcular endereço físico: $\text{physical\_address} = (f \times \text{page\_size}) + d$.
     - Retornar $\text{physical\_address}$.

---

### 4.3. Tratamento de Falta de Página (Page Fault) e Swap
- **Passo a Passo:**
  1. A MMU sinaliza `PageFaultException` para a página $p$ do processo $P$.
  2. O `MemoryManager` procura um `Frame` livre na lista de molduras físicas.
  3. Se não houver moldura livre:
     - Executar o algoritmo de substituição de páginas (LRU ou Segunda Chance) para eleger uma moldura vítima.
     - Localizar a entrada de página correspondente à moldura vítima.
     - Se o bit `dirty` da vítima for `True`, descarregar os dados da moldura para a partição de Swap simulada (`swap_out`).
     - Marcar a entrada da vítima como `present = False` e `frame_id = None`.
  4. Alocar a moldura agora disponível para a página $p$.
  5. Carregar os dados da página $p$ a partir do Swap simulado (`swap_in`).
  6. Atualizar a entrada da página $p$: `frame_id = frame`, `present = True`, `dirty = False`, `referenced = True`.
  7. Retomar a execução da instrução da MMU.

---

### 4.4. Algoritmos de Substituição de Páginas

#### A. LRU (Least Recently Used)
- Elege a página na memória cuja última referência (`last_access`) ocorreu no menor instante de tempo:
  $$\text{Vítima} = \arg\min_{e \in \text{Páginas Presentes}} (e.\text{last\_access})$$

#### B. Segunda Chance (Clock Algorithm)
- Mantém um ponteiro circular apontando para as molduras físicas em uso.
- **Passo a Passo:**
  1. Inspecionar a página apontada pelo ponteiro do relógio.
  2. Se `referenced == False`: Esta página é a vítima escolhida. Avançar o ponteiro e retornar a vítima.
  3. Se `referenced == True`:
     - Limpar o bit (`referenced = False`).
     - Conceder uma segunda chance à página.
     - Avançar o ponteiro para a próxima moldura e repetir o passo 1.
