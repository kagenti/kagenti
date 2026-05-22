# Environment Variables Import Feature Design

## Overview

This design document outlines a comprehensive solution for importing environment variable definitions from local filesystem or remote URLs into the Kagenti UI, with support for standard `.env` files and extended JSON syntax for Kubernetes secret/configMap references.

## Requirements

1. **Import `.env` files** from local filesystem or remote URLs
2. **Extended `.env` format** to support JSON values for `secretKeyRef` and `configMapKeyRef`
3. **Display imported variables** in the "Environment Variables" section (editable)
4. **Delete functionality** for individual environment variables
5. **Support standard and extended formats** simultaneously

## Example `.env` File Format

### Standard Format
```env
MCP_URL=http://weather-tool:8080/mcp
LLM_MODEL=llama3.2
PORT=8000
```

### Extended Format (Kubernetes References)

When you need to reference values stored in Kubernetes Secrets or ConfigMaps, use JSON format for the value. The JSON must be enclosed in single quotes to prevent shell interpretation.

**Format Rules:**
- The entire JSON object must be enclosed in **single quotes** (`'...'`)
- Use **double quotes** for JSON keys and string values
- Do not add spaces around the `=` sign (standard .env convention)
- JSON must be valid and properly escaped

**Secret Reference Format:**
```env
# Reference a key from a Kubernetes Secret
VARIABLE_NAME='{"valueFrom": {"secretKeyRef": {"name": "secret-name", "key": "key-name"}}}'
```

**ConfigMap Reference Format:**
```env
# Reference a key from a Kubernetes ConfigMap
VARIABLE_NAME='{"valueFrom": {"configMapKeyRef": {"name": "configmap-name", "key": "key-name"}}}'
```

**Complete Example:**
```env
# Standard direct values
MCP_URL=http://weather-tool:8080/mcp
PORT=8000
LOG_LEVEL=INFO

# Reference to OpenAI API key stored in a Secret
OPENAI_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'

# Reference to LLM API key from the same Secret
LLM_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'

# Reference to configuration from a ConfigMap
APP_CONFIG='{"valueFrom": {"configMapKeyRef": {"name": "app-settings", "key": "config.json"}}}'
```

**Important Notes:**
1. The Secret or ConfigMap must exist in the same namespace as your agent
2. The agent's ServiceAccount must have permission to read the referenced Secret/ConfigMap
3. If the referenced key doesn't exist, the pod will fail to start
4. You can mix standard values and references in the same `.env` file

## Architecture

### Component Structure

```
┌─────────────────────────────────────────────────────────────┐
│                   Frontend (React/TypeScript)                │
├─────────────────────────────────────────────────────────────┤
│  ImportAgentPage.tsx                                         │
│    ├── EnvImportModal (new component)                        │
│    │   ├── File upload (local)                               │
│    │   ├── URL input (remote)                                │
│    │   └── Preview & validation                              │
│    │                                                          │
│    └── EnvironmentVariablesSection (enhanced)                │
│        ├── Existing manual entry                             │
│        ├── Import button → EnvImportModal                    │
│        ├── Edit capabilities                                 │
│        └── Delete functionality                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI/Python)                  │
├─────────────────────────────────────────────────────────────┤
│  /api/agents/parse-env (new endpoint)                        │
│    ├── Parse .env content                                    │
│    ├── Validate JSON values                                  │
│    └── Return structured EnvVar list                         │
│                                                              │
│  /api/agents/fetch-env-url (new endpoint)                    │
│    ├── Fetch from remote URL                                 │
│    ├── Security validations                                  │
│    └── Return file content                                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Kubernetes Deployment                       │
├─────────────────────────────────────────────────────────────┤
│  spec:                                                        │
│    template:                                                  │
│      spec:                                                    │
│        containers:                                            │
│          - env:                                               │
│              - name: MCP_URL                                  │
│                value: "http://weather-tool:8080/mcp"         │
│              - name: SECRET_KEY                               │
│                valueFrom:                                     │
│                  secretKeyRef:                                │
│                    name: openai-secret                        │
│                    key: apikey                                │
└─────────────────────────────────────────────────────────────┘
```

---

## Detailed Implementation Design

### 1. Frontend Components

#### 1.1 New Component: `EnvImportModal.tsx`

**Location**: `/Users/paolo/Projects/aiplatform/kagenti/kagenti/ui-v2/src/components/EnvImportModal.tsx`

**Purpose**: Modal dialog for importing environment variables from file or URL

**Features**:
- Tab interface: "Upload File" and "From URL"
- File upload with drag-and-drop support
- URL input with fetch button
- Preview section showing parsed variables
- Validation feedback
- Import/Cancel actions

**Key Props**:
```typescript
interface EnvImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (envVars: EnvVar[]) => void;
}
```

**State Management**:
```typescript
const [activeTab, setActiveTab] = useState<'file' | 'url'>('file');
const [fileContent, setFileContent] = useState<string>('');
const [url, setUrl] = useState<string>('');
const [previewVars, setPreviewVars] = useState<EnvVar[]>([]);
const [isLoading, setIsLoading] = useState(false);
const [error, setError] = useState<string | null>(null);
```

#### 1.2 Enhanced Data Model: `EnvVar` Interface

**Location**: Update in `/Users/paolo/Projects/aiplatform/kagenti/kagenti/ui-v2/src/pages/ImportAgentPage.tsx`

**Enhanced Interface**:
```typescript
interface EnvVar {
  name: string;
  value?: string;  // For simple values
  valueFrom?: {    // For Kubernetes references
    secretKeyRef?: {
      name: string;
      key: string;
    };
    configMapKeyRef?: {
      name: string;
      key: string;
    };
  };
}
```

#### 1.3 Enhanced: Environment Variables Section in `ImportAgentPage.tsx`

**Updates Required**:

1. **Add Import Button**:
   ```tsx
   <Button
     variant="secondary"
     icon={<UploadIcon />}
     onClick={() => setShowImportModal(true)}
   >
     Import from File/URL
   </Button>
   ```

2. **Enhanced Display Logic**:
   - Show "Value" column for simple values
   - Show "Source" column indicating: "Value", "Secret", or "ConfigMap"
   - Show reference details for Kubernetes sources
   - Add delete button for each row

3. **Edit Functionality**:
   - Allow switching between value types
   - Provide dropdown to select: "Direct Value", "Secret Reference", "ConfigMap Reference"
   - Conditional form fields based on selection

**Enhanced UI Structure**:
```tsx
{envVars.map((env, index) => (
  <Grid hasGutter key={index}>
    <GridItem span={3}>
      <TextInput 
        value={env.name}
        onChange={(_e, value) => updateEnvVar(index, 'name', value)}
        placeholder="VAR_NAME"
      />
    </GridItem>
    <GridItem span={2}>
      <FormSelect
        value={getEnvVarType(env)}
        onChange={(_e, value) => handleTypeChange(index, value)}
      >
        <FormSelectOption value="value" label="Direct Value" />
        <FormSelectOption value="secret" label="Secret" />
        <FormSelectOption value="configMap" label="ConfigMap" />
      </FormSelect>
    </GridItem>
    <GridItem span={6}>
      {renderValueInput(env, index)}
    </GridItem>
    <GridItem span={1}>
      <Button 
        variant="plain" 
        onClick={() => removeEnvVar(index)}
      >
        <TrashIcon />
      </Button>
    </GridItem>
  </Grid>
))}
```

---

### 2. Backend API Endpoints

#### 2.1 New Endpoint: `POST /api/agents/parse-env`

**Purpose**: Parse `.env` file content and return structured environment variables

**Request Body**:
```python
class ParseEnvRequest(BaseModel):
    content: str  # Raw .env file content
```

**Response**:
```python
class ParseEnvResponse(BaseModel):
    envVars: List[EnvVar]
    warnings: Optional[List[str]] = None  # Parsing warnings
```

**Implementation Logic**:

```python
@router.post("/parse-env", response_model=ParseEnvResponse)
async def parse_env_file(request: ParseEnvRequest) -> ParseEnvResponse:
    """
    Parse .env file content and return structured environment variables.
    Supports:
    - Standard KEY=value format
    - Extended JSON format for secretKeyRef and configMapKeyRef
    """
    env_vars = []
    warnings = []
    
    lines = request.content.strip().split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Skip empty lines and comments
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Parse KEY=VALUE
        if '=' not in line:
            warnings.append(f"Line {line_num}: Invalid format, missing '='")
            continue
        
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        
        # Try to parse as JSON (for extended format)
        if value.startswith('{') and value.endswith('}'):
            try:
                parsed = json.loads(value)
                if 'valueFrom' in parsed:
                    env_var = {'name': key, 'valueFrom': parsed['valueFrom']}
                    env_vars.append(env_var)
                    continue
            except json.JSONDecodeError:
                warnings.append(f"Line {line_num}: Invalid JSON in value")
        
        # Standard value
        env_vars.append({'name': key, 'value': value})
    
    return ParseEnvResponse(envVars=env_vars, warnings=warnings if warnings else None)
```

#### 2.2 New Endpoint: `POST /api/agents/fetch-env-url`

**Purpose**: Fetch `.env` file from remote URL

**Request Body**:
```python
class FetchEnvUrlRequest(BaseModel):
    url: str
```

**Response**:
```python
class FetchEnvUrlResponse(BaseModel):
    content: str
    url: str
```

**Implementation Logic**:

```python
import httpx

@router.post("/fetch-env-url", response_model=FetchEnvUrlResponse)
async def fetch_env_from_url(request: FetchEnvUrlRequest) -> FetchEnvUrlResponse:
    """
    Fetch .env file content from a remote URL.
    Supports HTTP/HTTPS URLs with basic security validations.
    """
    # Security validation
    parsed_url = urlparse(request.url)
    if parsed_url.scheme not in ['http', 'https']:
        raise HTTPException(
            status_code=400,
            detail="Only HTTP/HTTPS URLs are supported"
        )
    
    # Prevent SSRF attacks - block private IPs
    try:
        ip = socket.gethostbyname(parsed_url.hostname)
        if ipaddress.ip_address(ip).is_private:
            raise HTTPException(
                status_code=400,
                detail="Private IP addresses are not allowed"
            )
    except socket.gaierror:
        pass  # Allow domain names that can't be resolved yet
    
    # Fetch content
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(request.url)
            response.raise_for_status()
            
            # Validate content type (optional)
            content_type = response.headers.get('content-type', '')
            if 'text' not in content_type and 'application/octet-stream' not in content_type:
                logging.warning(f"Unexpected content-type: {content_type}")
            
            return FetchEnvUrlResponse(
                content=response.text,
                url=request.url
            )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch URL: {str(e)}"
        )
```

#### 2.3 Update: Enhanced `EnvVar` Model

**Location**: `/Users/paolo/Projects/aiplatform/kagenti/kagenti/backend/app/routers/agents.py`

**Enhanced Model**:
```python
from typing import Optional, Dict, Any

class SecretKeyRef(BaseModel):
    """Reference to a key in a Secret."""
    name: str
    key: str

class ConfigMapKeyRef(BaseModel):
    """Reference to a key in a ConfigMap."""
    name: str
    key: str

class EnvVarSource(BaseModel):
    """Source for environment variable value."""
    secretKeyRef: Optional[SecretKeyRef] = None
    configMapKeyRef: Optional[ConfigMapKeyRef] = None

class EnvVar(BaseModel):
    """Environment variable with support for direct values and references."""
    name: str
    value: Optional[str] = None
    valueFrom: Optional[EnvVarSource] = None
    
    @validator('valueFrom', 'value', always=True)
    def check_value_or_value_from(cls, v, values):
        """Ensure either value or valueFrom is provided, but not both."""
        has_value = values.get('value') is not None
        has_value_from = v is not None
        
        if not has_value and not has_value_from:
            raise ValueError('Either value or valueFrom must be provided')
        if has_value and has_value_from:
            raise ValueError('Cannot specify both value and valueFrom')
        
        return v
```

#### 2.4 Update: Agent Manifest Building

**Update in**: `build_agent_manifest()` function

**Enhanced Environment Variable Processing**:
```python
def build_agent_manifest(
    request: CreateAgentRequest, build_ref_name: Optional[str] = None
) -> dict:
    """Build an Agent CRD manifest."""
    
    # Build environment variables with support for valueFrom
    env_vars = list(DEFAULT_ENV_VARS)
    if request.envVars:
        for ev in request.envVars:
            if ev.value is not None:
                # Direct value
                env_vars.append({"name": ev.name, "value": ev.value})
            elif ev.valueFrom is not None:
                # Reference to Secret or ConfigMap
                env_entry = {"name": ev.name, "valueFrom": {}}
                
                if ev.valueFrom.secretKeyRef:
                    env_entry["valueFrom"]["secretKeyRef"] = {
                        "name": ev.valueFrom.secretKeyRef.name,
                        "key": ev.valueFrom.secretKeyRef.key,
                    }
                elif ev.valueFrom.configMapKeyRef:
                    env_entry["valueFrom"]["configMapKeyRef"] = {
                        "name": ev.valueFrom.configMapKeyRef.name,
                        "key": ev.valueFrom.configMapKeyRef.key,
                    }
                
                env_vars.append(env_entry)
    
    # ... rest of manifest building
```

---

### 3. Frontend Service Layer

#### 3.1 New API Client Methods

**Location**: `/Users/paolo/Projects/aiplatform/kagenti/kagenti/ui-v2/src/services/api.ts`

**Add to `agentService` object**:

```typescript
export const agentService = {
  // ... existing methods
  
  parseEnvFile: async (content: string): Promise<ParseEnvResponse> => {
    const response = await apiClient.post<ParseEnvResponse>(
      '/agents/parse-env',
      { content }
    );
    return response.data;
  },
  
  fetchEnvFromUrl: async (url: string): Promise<FetchEnvUrlResponse> => {
    const response = await apiClient.post<FetchEnvUrlResponse>(
      '/agents/fetch-env-url',
      { url }
    );
    return response.data;
  },
};

interface ParseEnvResponse {
  envVars: EnvVar[];
  warnings?: string[];
}

interface FetchEnvUrlResponse {
  content: string;
  url: string;
}
```

---

### 4. User Workflow

#### Scenario 1: Import from Local File

1. User clicks "Import from File/URL" button in Environment Variables section
2. Modal opens with "Upload File" tab active
3. User drags `.env` file or clicks to browse
4. Frontend reads file content using FileReader API
5. Frontend calls `/api/agents/parse-env` with file content
6. Backend parses and returns structured `EnvVar[]` with any warnings
7. Modal shows preview of parsed variables
8. User reviews and clicks "Import"
9. Variables are merged with existing `envVars` state
10. User can edit or delete any variable before final submission

#### Scenario 2: Import from URL

1. User clicks "Import from File/URL" button
2. Modal opens, user switches to "From URL" tab
3. User enters URL (e.g., `https://raw.githubusercontent.com/kagenti/agent-examples/main/a2a/git_issue_agent/.env.openai`)
4. User clicks "Fetch"
5. Frontend calls `/api/agents/fetch-env-url`
6. Backend fetches content with security validations
7. Frontend automatically calls `/api/agents/parse-env` with fetched content
8. Modal shows preview
9. User imports variables

#### Scenario 3: Edit Environment Variable Type

1. User has imported/added environment variables
2. User clicks dropdown next to variable showing "Direct Value"
3. Changes to "Secret"
4. UI replaces value input with two fields: "Secret Name" and "Key"
5. User fills in: `openai-secret` and `apikey`
6. On save, backend converts to proper Kubernetes format

#### Scenario 4: Delete Environment Variable

1. User reviews environment variables list
2. User clicks trash icon next to unwanted variable
3. Variable is removed from state
4. No backend call until final agent creation

---

### 5. Security Considerations

#### 5.1 SSRF Protection (Server-Side Request Forgery)

**Implementation in `/api/agents/fetch-env-url`**:

```python
# Block private IP ranges
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
]

def is_ip_blocked(ip_str: str) -> bool:
    """Check if IP is in blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in BLOCKED_IP_RANGES)
    except ValueError:
        return False
```

#### 5.2 Content Validation

- Limit file size (max 1MB)
- Validate `.env` format
- Sanitize values before display
- Timeout on URL fetches (10 seconds)

#### 5.3 Kubernetes Security

- Validate secret/configMap names follow Kubernetes naming conventions
- Ensure referenced secrets exist in target namespace (optional backend validation)
- Support RBAC for secret access

---

### 6. Testing Strategy

#### 6.1 Unit Tests

**Frontend**:
- `EnvImportModal.test.tsx`: Test file upload, URL fetch, parsing preview
- `ImportAgentPage.test.tsx`: Test env var CRUD operations
- Test edge cases: empty files, malformed JSON, large files

**Backend**:
- `test_parse_env.py`: Test standard and extended `.env` parsing
- `test_fetch_env_url.py`: Test URL fetching with mocked responses
- Test security: SSRF protection, content validation

#### 6.2 Integration Tests

- End-to-end: Import file → Create agent → Verify Kubernetes env vars
- Test secret references: Create secret → Import env with secretKeyRef → Deploy
- Test merge behavior: Existing vars + imported vars

#### 6.3 Manual Testing Checklist

- [ ] Import standard `.env` file with 10+ variables
- [ ] Import extended `.env` with secret/configMap references
- [ ] Fetch from GitHub raw URL
- [ ] Edit imported variable from value to secret reference
- [ ] Delete imported variable
- [ ] Create agent with mixed env var types
- [ ] Verify Kubernetes Agent CR has correct env structure
- [ ] Test error handling: invalid URL, network timeout, parse errors

---

### 7. Implementation Phases

#### Phase 1: Backend Foundation (Week 1)
- [ ] Implement enhanced `EnvVar` models with `valueFrom` support
- [ ] Implement `/api/agents/parse-env` endpoint
- [ ] Implement `/api/agents/fetch-env-url` endpoint with security
- [ ] Update `build_agent_manifest()` to handle `valueFrom`
- [ ] Write backend unit tests

#### Phase 2: Frontend Components (Week 1-2)
- [ ] Create `EnvImportModal.tsx` component
- [ ] Implement file upload with drag-and-drop
- [ ] Implement URL fetch integration
- [ ] Add parsing preview and validation feedback
- [ ] Update API service layer

#### Phase 3: UI Integration (Week 2)
- [ ] Enhance Environment Variables section in `ImportAgentPage.tsx`
- [ ] Update `EnvVar` interface
- [ ] Implement type dropdown (Value/Secret/ConfigMap)
- [ ] Implement conditional form fields
- [ ] Add delete functionality
- [ ] Integrate `EnvImportModal`

#### Phase 4: Testing & Documentation (Week 2-3)
- [ ] Write frontend unit tests
- [ ] Write integration tests
- [ ] Perform manual testing
- [ ] Update user documentation
- [ ] Create demo video/screenshots

---

### 8. File Structure Summary

#### New Files
```
kagenti/ui-v2/src/components/
  └── EnvImportModal.tsx              # New modal component

kagenti/ui-v2/src/components/
  └── EnvImportModal.test.tsx         # Tests

kagenti/backend/app/routers/
  └── (agents.py - enhanced)          # New endpoints + models
```

#### Modified Files
```
kagenti/ui-v2/src/pages/
  └── ImportAgentPage.tsx             # Enhanced env var section

kagenti/ui-v2/src/services/
  └── api.ts                          # New API methods

kagenti/backend/app/routers/
  └── agents.py                       # Enhanced models & manifest building
```

---

### 9. Example Usage

#### Example 1: Standard .env File

**File**: `my-agent.env`
```env
# LLM Configuration
LLM_MODEL=gpt-4
LLM_TEMPERATURE=0.7
MAX_TOKENS=2000

# MCP Tools
MCP_URL=http://weather-tool:8080/mcp
MCP_TIMEOUT=30

# Application
PORT=8000
LOG_LEVEL=info
```

**Result**: 7 environment variables imported with direct values

#### Example 2: Extended .env with Secrets

**File**: `agent-with-secrets.env`
```env
# Direct values
PORT=8000
MCP_URL=http://weather-tool:8080/mcp

# Secret references (JSON format)
OPENAI_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'
DATABASE_PASSWORD='{"valueFrom": {"secretKeyRef": {"name": "db-credentials", "key": "password"}}}'

# ConfigMap reference
APP_CONFIG='{"valueFrom": {"configMapKeyRef": {"name": "app-settings", "key": "config.json"}}}'
```

**Resulting Kubernetes Manifest**:
```yaml
spec:
  podTemplateSpec:
    spec:
      containers:
        - name: agent
          env:
            - name: PORT
              value: "8000"
            - name: MCP_URL
              value: "http://weather-tool:8080/mcp"
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-secret
                  key: apikey
            - name: DATABASE_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: password
            - name: APP_CONFIG
              valueFrom:
                configMapKeyRef:
                  name: app-settings
                  key: config.json
```

---

## Conclusion

This design provides a comprehensive solution for importing environment variables from local files or remote URLs, with full support for Kubernetes secret and configMap references. The implementation is split into manageable phases with clear security considerations and testing strategies.

The solution maintains backward compatibility with existing manual environment variable entry while providing powerful new capabilities for agent developers to quickly configure agents using standardized `.env` files.
