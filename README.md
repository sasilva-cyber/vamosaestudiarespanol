# Vamos a Estudiar Español

Novo site/blog oficial do **Vamos a Estudiar Español**, preparado para GitHub Pages e migração do Blogger.

## Arquitetura

- **Jekyll + GitHub Pages** para posts, layouts, SEO, feed e sitemap.
- Identidade visual alinhada ao Espaço de Prática: vinho, dourado, creme, marca `Ñ` e títulos serifados.
- URLs de posts no padrão histórico do Blogger: `/ano/mês/slug.html`.
- Layout responsivo com navbar, cabeçalho editorial, sidebar e rodapé.
- Compartilhamento em WhatsApp, Facebook, Pinterest e Instagram/folha nativa de compartilhamento.
- Postagens relacionadas ao fim de cada artigo.
- Sidebar com arquivo mensal, últimos posts, mais visualizadas, Facebook e últimos vídeos do YouTube.
- Integração dos vídeos com o endpoint já usado pelo Espaço de Prática.

## Estrutura principal

```text
_config.yml
_layouts/
  default.html
  post.html
_posts/
assets/
  css/style.css
  js/site.js
index.html
arquivo.html
sobre.html
404.html
robots.txt
```

## Migração do Blogger

O acervo deve ser convertido para arquivos em `_posts/`, mantendo para cada publicação:

- título;
- data e horário originais;
- slug/permalink original;
- conteúdo;
- imagens;
- categoria e tags;
- descrição/meta description quando disponível.

Para um post cuja URL atual seja, por exemplo, `/2024/12/exemplo.html`, use no front matter:

```yaml
permalink: /2024/12/exemplo.html
```

Isso evita quebrar links externos e reduz o risco de perda de SEO durante a migração.

## Publicação e domínio

Não altere o DNS do domínio enquanto o acervo ainda estiver em migração.

Sequência recomendada:

1. importar e revisar as postagens do Blogger;
2. validar navegação, imagens, links internos, metadados e URLs;
3. mesclar a branch de implementação em `main`;
4. habilitar GitHub Pages para a branch `main` na raiz do repositório;
5. configurar `vamosaestudiarespanol.com.br` como domínio personalizado em **Settings → Pages**;
6. somente depois ajustar os registros DNS no provedor do domínio;
7. habilitar HTTPS quando o certificado estiver disponível;
8. validar sitemap e cobertura no Google Search Console.

> O arquivo `CNAME` deve ser criado/configurado no momento da ativação do domínio personalizado, não durante o desenvolvimento, para evitar uma troca prematura.

## Mais visualizadas

O componente já existe na sidebar. Sem um endpoint de ranking configurado, ele usa posts marcados com `popular: true` como fallback editorial. O campo `popular_posts_api` em `_config.yml` permite conectar posteriormente um endpoint de analytics/Supabase com dados reais de visualização.

## Desenvolvimento local

Com Ruby e Bundler instalados:

```bash
bundle install
bundle exec jekyll serve
```

O site ficará disponível em `http://localhost:4000`.
