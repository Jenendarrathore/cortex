import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    { type: 'doc', id: 'intro', label: 'Introduction' },
    { type: 'doc', id: 'architecture', label: 'Architecture' },
    {
      type: 'category',
      label: 'Setup',
      collapsed: false,
      items: [
        { type: 'doc', id: 'setup/machine-requirements', label: 'Machine Requirements' },
        { type: 'doc', id: 'setup/installation',         label: 'Installation' },
        { type: 'doc', id: 'setup/configuration',        label: 'Configuration' },
      ],
    },
    {
      type: 'category',
      label: 'RAG Backend',
      items: [
        { type: 'doc', id: 'rag-backend/overview',      label: 'Overview' },
        { type: 'doc', id: 'rag-backend/api-reference', label: 'API Reference' },
        { type: 'doc', id: 'rag-backend/data-model',    label: 'Data Model' },
      ],
    },
    {
      type: 'category',
      label: 'MCP (Claude Desktop)',
      items: [
        { type: 'doc', id: 'mcp/overview',             label: 'Overview' },
        { type: 'doc', id: 'mcp/tools',                label: 'Tools' },
        { type: 'doc', id: 'mcp/claude-desktop-setup', label: 'Claude Desktop Setup' },
      ],
    },
    {
      type: 'category',
      label: 'Admin UI',
      items: [
        { type: 'doc', id: 'rag-ui/overview', label: 'Overview' },
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      items: [
        { type: 'doc', id: 'guides/how-it-works',        label: 'How It Works' },
        { type: 'doc', id: 'guides/ingesting-documents', label: 'Ingesting Documents' },
        { type: 'doc', id: 'guides/searching',           label: 'Searching & Querying' },
      ],
    },
    { type: 'doc', id: 'make-commands', label: 'Make Commands' },
  ],
};

export default sidebars;
