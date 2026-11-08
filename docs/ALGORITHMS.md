# ESPECIFICAÇÃO DE ALGORITMOS E CONTRATOS LÓGICOS — OS SIMULATOR

> **Status:** Especificação Oficial Consolidada (Fase 0.1)  
> **Objetivo:** Estabelecer a especificação matemática, formal e algorítmica de todas as operações computacionais do simulador em suas quatro etapas acadêmicas, incorporando portas, adaptadores, origens de páginas e padrões de segurança modernos.

---

## 1. SUBSISTEMA DE SISTEMA DE ARQUIVOS (ETAPA 1)

### 1.1. Alocação Contígua
- **Objetivo:** Alocar um conjunto de blocos fisicamente adjacentes para armazenar um arquivo.
- **Entradas:** `file_size: int` (bytes), `block_size: int` (padrão: 4.096 bytes), `block_device: BlockDevicePort`.
- **Saídas:** `allocated_block_ids: List[int]` ou exceção de espaço contíguo insuficiente.
- **Passo a Passo:**
  1. Calcular o número de blocos de dados necessários: $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Consultar o mapa de blocos livres do `BlockDevicePort`.
  3. Localizar o primeiro intervalo contíguo de tamanho $\ge N$ (*First-Fit*) ou o menor intervalo $\ge N$ (*Best-Fit*).
  4. Se nenhum intervalo contíguo satisfizer $N$, lançar `DiskFragmentationException` (fragmentação externa impedindo alocação).
  5. Reservar os $N$ blocos contíguos e associá-los ao `Inode`.
- **Complexidade:** $O(M)$ onde $M$ é o total de blocos do dispositivo.

---

### 1.2. Alocação Encadeada (FAT — File Allocation Table)
- **Objetivo:** Alocar blocos arbitrários não adjacentes interligados por ponteiros em uma tabela centralizada.
- **Passo a Passo:**
  1. Calcular $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Coletar os primeiros $N$ blocos livres disponíveis no dispositivo de blocos.
  3. Atualizar a tabela FAT: para $i$ de $0$ a $N-2$, `fat_table[blocks[i]] = blocks[i+1]`.
  4. Definir o último bloco como fim de arquivo: `fat_table[blocks[N-1]] = EOF` (`-1`).
  5. Gravar o ID do primeiro bloco (`blocks[0]`) no `Inode`.
- **Complexidade:** Alocação $O(N)$; leitura aleatória do k-ésimo bloco requer travessia encadeada $O(k)$.

---

### 1.3. Alocação Indexada (i-node com Bloco de Índices Dedicado)
- **Objetivo:** Manter todos os ponteiros de blocos de um arquivo centralizados em um bloco físico de índices dedicado.
- **Entradas:** `file_size: int`, `block_size: int`, `block_device: BlockDevicePort`.
- **Saídas:** `index_block_id: int`, `allocated_data_blocks: List[int]`.
- **Passo a Passo:**
  1. Calcular o total de blocos de dados necessários: $N = \lceil \text{file\_size} / \text{block\_size} \rceil$.
  2. Alocar 1 bloco físico exclusivo para armazenar os índices de blocos (`index_block_id = block_device.allocate_block()`).
  3. Alocar $N$ blocos físicos de dados em quaisquer posições livres disponíveis.
  4. Gravar a lista de $N$ IDs de dados no conteúdo do bloco de índices.
  5. Registrar o `index_block_id` e a lista de blocos no `Inode`.
- **Complexidade:** Acesso aleatório a qualquer bloco lógico em $O(1)$ diretamente via índice.

---

### 1.4. Métricas Formais de Fragmentação e Ocupação de Armazenamento
Para evitar divergências na interpretação acadêmica e técnica:
1. **Espaço Ocupado pelos Dados ($E_{\text{dados}}$):**
   $$E_{\text{dados}} = \text{file\_size} \quad (\text{bytes reais da carga útil})$$
2. **Sobrecarga de Metadados e Indexação ($S_{\text{meta}}$):**
   $$S_{\text{meta}} = (\text{qtd\_blocos\_indice} \times \text{block\_size}) + \text{tamanho da entrada na tabela de i-nodes}$$
3. **Ocupação Física Total no Disco ($O_{\text{total}}$):**
   $$O_{\text{total}} = (N_{\text{dados}} + N_{\text{indice}}) \times \text{block\_size}$$
4. **Fragmentação Interna ($FI$):**
   $$FI = (N_{\text{dados}} \times \text{block\_size}) - \text{file\_size}$$
   *Exemplo oficial:* Para um arquivo de 10 KB ($10.240\text{ bytes}$) com blocos de 4 KB ($4.096\text{ bytes}$):
   $$N_{\text{dados}} = \lceil 10.240 / 4.096 \rceil = 3\text{ blocos}$$
   $$\text{Espaço alocado para dados} = 3 \times 4.096 = 12.288\text{ bytes}$$
   $$FI = 12.288 - 10.240 = 2.048\text{ bytes}$$
5. **Fragmentação Externa ($FE$):**
   - *Métrica Geral do Disco:* Soma dos bytes livres espalhados em blocos isolados que não conseguem atender a uma solicitação contígua de tamanho $K$:
     $$FE_{\text{disco}} = \sum \text{bytes de todos os blocos livres} \quad (\text{quando nenhum segmento contíguo} \ge K)$$
   - *Métrica do Arquivo na Alocação Indexada:* Reportada oficialmente como **$0\text{ bytes}$**, pois a alocação indexada tem a propriedade fundamental de interligar blocos livres dispersos por meio de ponteiros, sem exigir adjacência física. Portanto, a fragmentação externa não impede a alocação de arquivos indexados.

---

## 2. SUBSISTEMA DE ENTRADA E SAÍDA (I/O) E ARMAZENAMENTO (ETAPA 2)

### 2.1. Escalonamento Mecânico de Disco (HDD)
- **FCFS:** Atendimento estrito na ordem de chegada da fila.
- **SSTF (Shortest Seek Time First):** A partir da posição atual do cabeçote, atende a requisição mais próxima:
  $$R^* = \arg\min_{R \in \text{Fila}} |\text{track}(R) - \text{cabeçote\_atual}|$$
  *Validação Oficial IO-001:* Início trilha 53, fila `[98, 183, 37, 122, 14]`. Percurso: $53 \to 37 \to 14 \to 98 \to 122 \to 183$. Total: $16 + 23 + 84 + 24 + 61 = 208\text{ trilhas}$.
- **SCAN (Elevador):** Deslocamento unidirecional até o limite da unidade atendendo requisições, inversão de sentido e atendimento do sentido oposto.
- **C-SCAN (Circular SCAN):** Deslocamento unidirecional até a borda; salto imediato para o início oposto sem atender requisições no retorno.

### 2.2. SSD e Wear Leveling
- Mantém contador de escritas por bloco físico: `write_cycles[block_id]`.
- Ao gravar, prioriza blocos livres com menor contador de desgaste.
- Caso a diferença $(\max(\text{write\_cycles}) - \min(\text{write\_cycles})) > \text{limiar}$, aciona *Wear Leveling Estático*, migrando dados frios para blocos desgastados e liberando blocos novos para gravações frequentes.

### 2.3. Controladores RAID e Reconstrução XOR
- **RAID 0:** Striping puro sem redundância.
- **RAID 1:** Espelhamento puro.
- **RAID 4:** Striping de dados com disco dedicado de paridade XOR.
- **RAID 5:** Striping de dados com paridade distribuída e rotativa entre $N$ discos.
- **Cálculo da Paridade XOR:**
  Para blocos de $K$ bytes, a paridade é calculada byte a byte:
  $$P[j] = D_0[j] \oplus D_1[j] \oplus \dots \oplus D_{N-2}[j]$$
- **Reconstrução On-The-Fly (Rebuild):**
  Se o Disco $k$ falhar, o bloco ausente $D_k$ é recuperado em tempo real pelo XOR dos blocos sobreviventes da faixa com o bloco de paridade:
  $$D_k[j] = P[j] \oplus \bigoplus_{m \neq k} D_m[j]$$

---

## 3. SUBSISTEMA DE SEGURANÇA E PROTEÇÃO (ETAPA 3)

### 3.1. Autenticação e Derivação de Chaves (PBKDF2-HMAC-SHA256)
- **Padrão Oficial:** PBKDF2-HMAC-SHA256 alinhado às recomendações do *OWASP Password Storage Cheat Sheet*.
- **Parâmetros:**
  - Salt individual aleatório: 16 bytes (`secrets.token_bytes(16)`).
  - Número de iterações de referência: **600.000 iterações** (armazenado nos metadados de cada credencial para permitir evolução futura de custo computacional).
  - Testes de desempenho no ambiente devem validar tempo de derivação adequado (~100-300 ms).
- **Verificação:** Comparação em tempo constante via `hmac.compare_digest(hash_calculado, hash_armazenado)` para imunidade a ataques de temporização (*timing attacks*).

---

### 3.2. Criptografia em Repouso (AES-256-GCM)
- **Padrão Oficial:** AES-256 no modo GCM (Galois/Counter Mode — AEAD).
- **Parâmetros e Estrutura:**
  - Nonce exclusivo: **12 bytes (96 bits)** gerado criptograficamente para cada gravação. Nunca reutilizar nonces com a mesma chave.
  - Tag de autenticação: **16 bytes (128 bits)** gerada automaticamente para validar integridade e autenticidade.
  - Formato no bloco simulado: `[12 bytes Nonce] + [16 bytes Tag] + [Ciphertext]`.
- **Separação de Chaves:** A chave utilizada para cifrar o arquivo **não** é o hash da senha de login do usuário. A chave de arquivo é derivada via HKDF/PBKDF2 com rótulo de contexto explícito (`info="file-encryption"`), isolando as funções de autenticação e confidencialidade.
- **Tratamento de Falhas:** Se o conteúdo cifrado for alterado ou corrompido, o GCM falha na verificação da tag e lança `InvalidTagException`, abortando a leitura e registrando alerta no `AuditLog`.
- **Dependência Autorizada:** Biblioteca `cryptography` autorizada para a Etapa 3.

---

### 3.3. Integridade e Antivírus Simulado
- **Detecção de Corrupção Acidental vs. Adulteração Maliciosa:**
  - *Corrupção Acidental:* Detectada por divergência entre o SHA-256 recalculado e o hash registrado no i-node.
  - *Adulteração Maliciosa:* Para prevenir que um invasor altere simultaneamente o bloco de dados e o hash de referência nos metadados, o Kernel mantém uma chave raiz protegida que assina os hashes via HMAC (`IntegrityRecord.hmac_signature`). Qualquer modificação não assinada pelo Kernel é detectada.
- **Antivírus Simulado (`antivirus_scan`):**
  - Percorre os blocos e compara padrões de bytes contra uma base de assinaturas simuladas (ex.: assinatura EICAR simulada). Emite relatório de arquivos íntegros, infectados e suspeitos.

---

## 4. SUBSISTEMA DE GERENCIAMENTO DE MEMÓRIA REAL E VIRTUAL (ETAPA 4)

### 4.1. Área Reservada Contígua e Compactação Deslizante (`memory_compact`)
- **Alocação:** First-Fit / Best-Fit sobre a lista ligada de `MemorySegment`.
- **Diagnóstico de Fragmentação Externa:**
  $$FE_{\text{mem}} = \text{Espaço Livre Total} - \text{Tamanho do Maior Segmento Livre Contíguo}$$
- **Algoritmo `memory_compact`:**
  1. Identificar segmentos alocados (`status == ALLOCATED`).
  2. Deslocar os segmentos contiguamente para a base da memória (após o Núcleo Base).
  3. Atualizar `start_address` e `end_address` de cada processo crítico/driver.
  4. Consolidar os buracos livres em um único segmento livre contíguo no topo da área reservada.

---

### 4.2. Paginação, MMU e Origens Válidas no Page Fault
- **Tradução:** $p = \lfloor \text{virtual\_address} / 4096 \rfloor$, $d = \text{virtual\_address} \pmod{4096}$.
- **Tratamento de Falta de Página (`present == False`):**
  1. Identificar a moldura livre. Se a RAM dinâmica estiver saturada, invocar substituição (LRU ou Segunda Chance).
  2. **Tratamento da Página Vítima:**
     - Se `dirty == False`: A página está limpa. Se possuir origem recuperável (`PROCESS_IMAGE`), é descartada da moldura sem gravação no Swap.
     - Se `dirty == True`: A página foi modificada. Deve ser obrigatoriamente gravada no Swap simulado via `BlockDevicePort`.
  3. **Carregamento da Página Requerida Conforme sua Origem Válida:**
     - *Origem `ZERO_FILL_ON_DEMAND`:* A moldura física é preenchida diretamente com zeros na RAM (`bytearray(4096)`). **Nenhuma leitura de Swap ou disco é acionada!**
     - *Origem `PROCESS_IMAGE`:* A página de código/dados é carregada do binário executável simulado.
     - *Origem `SWAP_STORAGE`:* A página já residiu na RAM e foi salva no Swap; é executado `swap_in` lendo o bloco de swap e liberando o slot correspondente.
  4. Atualizar `PageTableEntry`: `frame_id = frame`, `present = True`, `dirty = False`, `referenced = True`.

---

### 4.3. Algoritmos de Substituição de Páginas
- **LRU (Least Recently Used):** Elege a moldura cuja página possui o menor timestamp de último acesso (`last_access`).
- **Segunda Chance (Clock):** Percorre circularmente as molduras:
  - Se `referenced == False`: Vítima selecionada.
  - Se `referenced == True`: Concede segunda chance (`referenced = False`), avança ponteiro e continua.
