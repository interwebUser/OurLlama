CREATE TABLE IF NOT EXISTS toolchain (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  display_name text NOT NULL,
  description text,
  kind text NOT NULL DEFAULT 'editor',
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Seed toolchains (safe to rerun)
INSERT INTO toolchain (slug, display_name, description, kind) VALUES
  ('vscode+roo-code', 'VS Code + Roo Code', 'Agentic coding in VS Code using Roo Code.', 'editor'),
  ('vscode+continue', 'VS Code + Continue', 'VS Code assistant using Continue.', 'editor'),
  ('vscode+cline', 'VS Code + Cline', 'Agentic coding with Cline in VS Code.', 'editor'),
  ('vscode+copilot', 'VS Code + Copilot', 'Copilot inside VS Code.', 'editor'),
  ('cursor', 'Cursor', 'Cursor IDE with integrated AI workflows.', 'editor'),
  ('jetbrains+ai', 'JetBrains + AI Assistant', 'JetBrains IDEs with AI Assistant.', 'editor'),
  ('neovim+avante', 'Neovim + Avante', 'Neovim with Avante plugin.', 'editor'),
  ('cli+aider', 'CLI + Aider', 'Agentic coding in terminal using Aider.', 'cli'),
  ('openwebui+ollama', 'Open WebUI + Ollama', 'Chat UI for Ollama.', 'ui'),
  ('anythingllm+ollama', 'AnythingLLM + Ollama', 'AnythingLLM backed by Ollama.', 'ui'),
  ('n8n+ollama', 'n8n + Ollama', 'Automation workflows using n8n with Ollama.', 'automation')
ON CONFLICT (slug) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description  = EXCLUDED.description,
  kind         = EXCLUDED.kind;