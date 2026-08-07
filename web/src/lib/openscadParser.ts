const MAX_DEPTH = 64;

// Typing note: only the keys below are ever actually assigned as a token's
// `type`. Several call sites elsewhere in this file compare `token.type`
// against `TOKENS.COLON` / `TOKENS.DOT` / `TOKENS.TRUE` / `TOKENS.FALSE`,
// which this object has never declared — those comparisons have always
// evaluated against `undefined` and so have always been dead branches. That
// is pre-existing runtime behavior this pass must not change, so TOKENS is
// typed as an open string->string dictionary (rather than adding the missing
// keys, which would flip those branches live) and the unused keys stay absent.
const TOKENS: Record<string, string> = {
  IDENT: 'IDENT',
  NUMBER: 'NUMBER',
  STRING: 'STRING',
  LBRACE: 'LBRACE',
  RBRACE: 'RBRACE',
  LPAREN: 'LPAREN',
  RPAREN: 'RPAREN',
  LBRACKET: 'LBRACKET',
  RBRACKET: 'RBRACKET',
  SEMICOLON: 'SEMICOLON',
  COMMA: 'COMMA',
  EQUALS: 'EQUALS',
  OPERATOR: 'OPERATOR',
  EOF: 'EOF',
};

const KEYWORDS = new Set([
  'cube', 'sphere', 'cylinder', 'polygon', 'polyhedron',
  'union', 'difference', 'intersection',
  'translate', 'rotate', 'scale', 'mirror', 'multmatrix',
  'linear_extrude', 'rotate_extrude',
  'function', 'module', 'for', 'let', 'if', 'echo', 'assert',
  'true', 'false',
]);

interface Token {
  type: string;
  value: string;
  line: number;
  col: number;
}

// A parsed parameter/object value: numbers, strings, idents (pass through as
// their raw string), booleans, nested vectors, or nested param objects.
export type OpenSCADValue =
  | number
  | string
  | boolean
  | null
  | OpenSCADValue[]
  | OpenSCADParams;

export interface OpenSCADParams {
  [key: string]: OpenSCADValue;
}

// Expression / statement AST node. The shapes below are heterogeneous by
// design (this parser was never given a single discriminated-union contract),
// so this stays a permissive "has a type tag, plus whatever fields that node
// kind carries" shape rather than a hand-enumerated union — precise enough to
// catch typos on `.type` while not fabricating structure the original code
// never guaranteed.
export interface OpenSCADNode {
  type: string;
  [key: string]: unknown;
}

export interface OpenSCADProgram {
  type: 'program';
  statements: OpenSCADNode[];
  warnings: string[];
}

class Tokenizer {
  src: string;
  pos: number;
  line: number;
  col: number;

  constructor(src: string) {
    this.src = src;
    this.pos = 0;
    this.line = 1;
    this.col = 0;
  }

  peek(offset = 0): string {
    return this.src[this.pos + offset] || '';
  }

  advance(): string {
    const ch = this.src[this.pos++];
    if (ch === '\n') { this.line++; this.col = 0; }
    else this.col++;
    return ch;
  }

  skipWhitespace(): void {
    while (/\s/.test(this.peek()) && this.peek() !== '\n') this.advance();
  }

  skipComment(): void {
    if (this.peek() === '/' && this.peek(1) === '/') {
      while (this.peek() && this.peek() !== '\n') this.advance();
    } else if (this.peek() === '/' && this.peek(1) === '*') {
      this.advance(); this.advance();
      while (this.peek() && !(this.peek() === '*' && this.peek(1) === '/')) this.advance();
      if (this.peek()) { this.advance(); this.advance(); }
    }
  }

  skipWhitespaceAndComments(): void {
    while (true) {
      const c = this.peek();
      if (c === '/' && (this.peek(1) === '/' || this.peek(1) === '*')) {
        this.skipComment();
      } else if (/\s/.test(c) && c !== '\n') {
        this.skipWhitespace();
      } else {
        break;
      }
    }
  }

  next(): Token {
    this.skipWhitespaceAndComments();
    const startLine = this.line;
    const startCol = this.col;

    if (this.pos >= this.src.length) {
      return { type: TOKENS.EOF, value: '', line: startLine, col: startCol };
    }

    const c = this.advance();

    switch (c) {
      case '{': return { type: TOKENS.LBRACE, value: '{', line: startLine, col: startCol };
      case '}': return { type: TOKENS.RBRACE, value: '}', line: startLine, col: startCol };
      case '(': return { type: TOKENS.LPAREN, value: '(', line: startLine, col: startCol };
      case ')': return { type: TOKENS.RPAREN, value: ')', line: startLine, col: startCol };
      case '[': return { type: TOKENS.LBRACKET, value: '[', line: startLine, col: startCol };
      case ']': return { type: TOKENS.RBRACKET, value: ']', line: startLine, col: startCol };
      case ';': return { type: TOKENS.SEMICOLON, value: ';', line: startLine, col: startCol };
      case ',': return { type: TOKENS.COMMA, value: ',', line: startLine, col: startCol };
      case '=': return { type: TOKENS.EQUALS, value: '=', line: startLine, col: startCol };
      case '\n': return { type: TOKENS.SEMICOLON, value: '\n', line: startLine, col: startCol };
    }

    if (c === '"' || c === "'") {
      const quote = c;
      let value = '';
      while (this.peek() && this.peek() !== quote) {
        if (this.peek() === '\\') { this.advance(); }
        value += this.advance();
      }
      if (this.peek() === quote) this.advance();
      return { type: TOKENS.STRING, value, line: startLine, col: startCol };
    }

    if (/[0-9]|-/.test(c)) {
      let value = c;
      while (/[0-9.eE+-]/.test(this.peek())) {
        value += this.advance();
      }
      return { type: TOKENS.NUMBER, value, line: startLine, col: startCol };
    }

    if (/[a-zA-Z_]/.test(c)) {
      let value = c;
      while (/[a-zA-Z0-9_]/.test(this.peek())) {
        value += this.advance();
      }
      const type_ = KEYWORDS.has(value) ? value.toUpperCase() : TOKENS.IDENT;
      return { type: type_, value, line: startLine, col: startCol };
    }

    if (/[+\-*/%<>!&|]/.test(c)) {
      let value = c;
      while (/[+\-*/%<>!&|]/.test(this.peek())) {
        value += this.advance();
      }
      return { type: TOKENS.OPERATOR, value, line: startLine, col: startCol };
    }

    return { type: TOKENS.IDENT, value: c, line: startLine, col: startCol };
  }
}

class Parser {
  tokenizer: Tokenizer;
  current: Token;
  warnings: string[];
  depth: number;
  _pushedBack: Token | undefined;

  constructor(src: string) {
    this.tokenizer = new Tokenizer(src);
    this.current = { type: TOKENS.EOF, value: '', line: 1, col: 0 };
    this.warnings = [];
    this.depth = 0;
    this._pushedBack = undefined;
    this.advance();
  }

  advance(): Token {
    this.current = this.tokenizer.next();
    return this.current;
  }

  expect(type_: string): Token {
    if (this.current.type === type_) {
      return this.advance();
    }
    throw new Error(`Expected ${type_} at line ${this.current.line}, got ${this.current.type} (${this.current.value})`);
  }

  parseNumber(): number | string {
    if (this.current.type === TOKENS.NUMBER) {
      const v = parseFloat(this.current.value);
      this.advance();
      return v;
    }
    if (this.current.type === TOKENS.IDENT) {
      return this.current.value;
    }
    return 0;
  }

  parseVector(): OpenSCADValue[] {
    const items: OpenSCADValue[] = [];
    this.expect(TOKENS.LBRACKET);
    while (this.current.type !== TOKENS.RBRACKET && this.current.type !== TOKENS.EOF) {
      if (this.current.type === TOKENS.NUMBER || this.current.type === TOKENS.IDENT) {
        items.push(this.parseNumber());
      } else if (this.current.type === TOKENS.LBRACKET) {
        items.push(this.parseVector());
      } else {
        this.advance();
      }
      if (this.current.type === TOKENS.COMMA) this.advance();
    }
    this.expect(TOKENS.RBRACKET);
    return items;
  }

  parseParams(): OpenSCADParams {
    const params: OpenSCADParams = {};
    if (this.current.type !== TOKENS.LPAREN) return params;
    this.advance();
    while (this.current.type !== TOKENS.RPAREN && this.current.type !== TOKENS.EOF) {
      if (this.current.type === TOKENS.IDENT) {
        const key = this.current.value;
        this.advance();
        let value: OpenSCADValue;
        if (this.current.type === TOKENS.EQUALS) {
          this.advance();
          value = this.parseParamValue();
        } else if (this.current.type === TOKENS.COMMA || this.current.type === TOKENS.RPAREN) {
          value = true;
        } else {
          value = this.parseParamValue();
        }
        params[key] = value;
      }
      if (this.current.type === TOKENS.COMMA) this.advance();
    }
    this.expect(TOKENS.RPAREN);
    return params;
  }

  parseParamValue(): OpenSCADValue {
    if (this.current.type === TOKENS.NUMBER) {
      return parseFloat(this.advance().value);
    }
    if (this.current.type === TOKENS.STRING) {
      return this.advance().value;
    }
    if (this.current.type === TOKENS.IDENT) {
      return this.advance().value;
    }
    if (this.current.type === TOKENS.LBRACKET) {
      return this.parseVector();
    }
    if (this.current.type === TOKENS.LBRACE) {
      return this.parseObject();
    }
    // See the TOKENS comment above: TRUE/FALSE were never declared keys, so
    // these have always been unreachable — preserved as-is.
    if (this.current.type === TOKENS.TRUE) { this.advance(); return true; }
    if (this.current.type === TOKENS.FALSE) { this.advance(); return false; }
    return null;
  }

  parseObject(): OpenSCADParams {
    const obj: OpenSCADParams = {};
    this.expect(TOKENS.LBRACE);
    while (this.current.type !== TOKENS.RBRACE && this.current.type !== TOKENS.EOF) {
      if (this.current.type === TOKENS.IDENT) {
        const key = this.current.value;
        this.advance();
        // See the TOKENS comment above: COLON was never declared, so the
        // `current.type === TOKENS.COLON` half of this condition has always
        // been unreachable — preserved as-is.
        if (this.current.type === TOKENS.EQUALS || this.current.type === TOKENS.COLON) {
          if (this.current.type === TOKENS.COLON) this.advance();
          else this.advance();
          obj[key] = this.parseParamValue();
        }
      }
      if (this.current.type === TOKENS.COMMA) this.advance();
    }
    this.expect(TOKENS.RBRACE);
    return obj;
  }

  parseStatement(): OpenSCADNode {
    const token = this.current;

    if (token.type === TOKENS.IDENT) {
      this.advance();
      if (this.current.type === TOKENS.EQUALS) {
        this.advance();
        const value = this.parseExpression();
        this.consumeSemicolon();
        return { type: 'assignment', name: token.value, value };
      }
      this.pushBack(token);
    }

    return this.parseExpression();
  }

  pushBack(token: Token): void {
    this._pushedBack = token;
  }

  parseExpression(): OpenSCADNode {
    this.depth++;
    if (this.depth > MAX_DEPTH) {
      this.warnings.push(`Recursion depth exceeded ${MAX_DEPTH} at line ${this.current.line}`);
      this.depth--;
      return { type: 'error', message: 'Recursion limit exceeded' };
    }

    const result = this.parseBinaryExpr();
    this.depth--;
    return result;
  }

  parseBinaryExpr(): OpenSCADNode {
    let left = this.parseUnary();

    while (this.current.type === TOKENS.OPERATOR && ['+', '-', '*', '/', '<', '>', '<=', '>=', '==', '!=', '&&', '||'].includes(this.current.value)) {
      const op = this.advance().value;
      const right = this.parseUnary();
      left = { type: 'binary', op, left, right };
    }

    return left;
  }

  parseUnary(): OpenSCADNode {
    if (this.current.type === TOKENS.OPERATOR && this.current.value === '!') {
      this.advance();
      return { type: 'unary', op: '!', arg: this.parseUnary() };
    }
    return this.parsePostfix();
  }

  parsePostfix(): OpenSCADNode {
    let expr = this.parsePrimary();

    while (true) {
      if (this.current.type === TOKENS.LPAREN) {
        const params = this.parseParams();
        expr = { type: 'call', func: expr, params };
      } else if (this.current.type === TOKENS.DOT) {
        // See the TOKENS comment above: DOT was never declared, so this
        // branch has always been unreachable — preserved as-is.
        this.advance();
        if (this.current.type === TOKENS.IDENT) {
          const method = this.current.value;
          this.advance();
          if (this.current.type === TOKENS.LPAREN) {
            const params = this.parseParams();
            expr = { type: 'call', func: { type: 'member', object: expr, property: method }, params };
          } else {
            expr = { type: 'member', object: expr, property: method };
          }
        }
      } else {
        break;
      }
    }

    return expr;
  }

  parsePrimary(): OpenSCADNode {
    const token = this.current;

    if (token.type === TOKENS.NUMBER) {
      this.advance();
      return { type: 'number', value: parseFloat(token.value) };
    }

    if (token.type === TOKENS.STRING) {
      this.advance();
      return { type: 'string', value: token.value };
    }

    if (token.type === TOKENS.IDENT) {
      this.advance();
      return { type: 'ident', name: token.value };
    }

    // See the TOKENS comment above: TRUE/FALSE were never declared, so these
    // have always been unreachable — preserved as-is.
    if (token.type === TOKENS.TRUE) { this.advance(); return { type: 'bool', value: true }; }
    if (token.type === TOKENS.FALSE) { this.advance(); return { type: 'bool', value: false }; }

    if (token.type === TOKENS.LBRACKET) {
      return { type: 'vector', value: this.parseVector() };
    }

    if (token.type === TOKENS.LBRACE) {
      return { type: 'object', value: this.parseObject() };
    }

    if (token.type === TOKENS.LPAREN) {
      this.advance();
      const expr = this.parseBinaryExpr();
      this.expect(TOKENS.RPAREN);
      return expr;
    }

    this.advance();
    return { type: 'null' };
  }

  consumeSemicolon(): void {
    while (this.current.type === TOKENS.SEMICOLON || this.current.type === TOKENS.EOF) {
      if (this.current.type === TOKENS.EOF) break;
      this.advance();
      if (this.current.type !== TOKENS.SEMICOLON) break;
    }
  }

  parseModuleCall(name: string): OpenSCADNode {
    this.consumeSemicolon();
    const params = this.parseParams();

    switch (name) {
      case 'cube':
        return { type: 'cube', params };
      case 'sphere':
        return { type: 'sphere', params };
      case 'cylinder':
        return { type: 'cylinder', params };
      case 'polygon':
        return { type: 'polygon', params };
      case 'polyhedron':
        return { type: 'polyhedron', params };
      case 'union':
        return { type: 'union', params };
      case 'difference':
        return { type: 'difference', params };
      case 'intersection':
        return { type: 'intersection', params };
      case 'translate':
        return { type: 'translate', params };
      case 'rotate':
        return { type: 'rotate', params };
      case 'scale':
        return { type: 'scale', params };
      case 'mirror':
        return { type: 'mirror', params };
      case 'multmatrix':
        return { type: 'multmatrix', params };
      case 'linear_extrude':
        return { type: 'linear_extrude', params };
      case 'rotate_extrude':
        return { type: 'rotate_extrude', params };
      default:
        this.warnings.push(`Unsupported module: ${name} at line ${this.current.line}`);
        return { type: 'unsupported', name, params };
    }
  }

  parse(): OpenSCADProgram {
    const statements: OpenSCADNode[] = [];

    while (this.current.type !== TOKENS.EOF) {
      try {
        if (this.current.type === TOKENS.SEMICOLON) {
          this.advance();
          continue;
        }

        if (this.current.type === TOKENS.IDENT) {
          const ident = this.current.value;
          this.advance();

          if (this.current.type === TOKENS.LPAREN) {
            const params = this.parseParams();
            this.consumeSemicolon();

            if (['cube', 'sphere', 'cylinder', 'polygon', 'polyhedron', 'union',
              'difference', 'intersection', 'translate', 'rotate', 'scale', 'mirror',
              'multmatrix', 'linear_extrude', 'rotate_extrude'].includes(ident)) {
              statements.push(this.parseModuleCall(ident));
              continue;
            }

            statements.push({ type: 'call', func: { type: 'ident', name: ident }, params });
            continue;
          }

          if (this.current.type === TOKENS.EQUALS) {
            this.advance();
            const value = this.parseBinaryExpr();
            this.consumeSemicolon();
            statements.push({ type: 'assignment', name: ident, value });
            continue;
          }

          this.pushBack({ type: TOKENS.IDENT, value: ident, line: this.current.line, col: this.current.col });
          const expr = this.parseBinaryExpr();
          this.consumeSemicolon();
          statements.push({ type: 'expr', value: expr });
          continue;
        }

        const expr = this.parseBinaryExpr();
        this.consumeSemicolon();
        statements.push({ type: 'expr', value: expr });
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        this.warnings.push(`Parse error: ${message} at line ${this.current.line}`);
        while (this.current.type !== TOKENS.SEMICOLON && this.current.type !== TOKENS.EOF) {
          this.advance();
        }
        this.advance();
      }
    }

    return { type: 'program', statements, warnings: this.warnings };
  }
}

export function parseOpenSCAD(src: string): OpenSCADProgram {
  const parser = new Parser(src);
  return parser.parse();
}

export { TOKENS };
