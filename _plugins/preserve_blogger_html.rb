# Preserva o HTML original dos conteúdos importados do Blogger.
#
# Os arquivos migrados usam extensão .md para conservar o fluxo histórico do
# repositório, mas o corpo deles já é HTML. Alguns posts antigos contêm HTML
# tolerado pelos navegadores (por exemplo, divs aninhadas em spans) que o
# Kramdown tenta normalizar e acaba exibindo como texto. Guardamos o corpo
# original antes da conversão Markdown e o restauramos após a conversão,
# antes da aplicação do layout.
module BloggerHtmlPreserver
  RAW_CONTENT_KEY = "_blogger_raw_content".freeze

  module_function

  def imported_from_blogger?(document)
    document.respond_to?(:data) && document.data["blogger_id"]
  end

  def capture(document)
    return unless imported_from_blogger?(document)

    document.data[RAW_CONTENT_KEY] = document.content.dup
  end

  def restore(document)
    return unless imported_from_blogger?(document)

    raw = document.data.delete(RAW_CONTENT_KEY)
    return unless raw

    # Durante a prévia do GitHub Pages o site vive em /vamosaestudiarespanol.
    # Prefixamos URLs internas apenas quando existe baseurl; no domínio oficial
    # baseurl é vazio e o HTML histórico permanece exatamente na raiz.
    baseurl = document.site.config["baseurl"].to_s.sub(%r{/$}, "")
    unless baseurl.empty?
      raw = raw.gsub(/\b(href|src)=(['"])\/(?!\/)([^'"]*)/i) do
        %(#{Regexp.last_match(1)}=#{Regexp.last_match(2)}#{baseurl}/#{Regexp.last_match(3)})
      end
    end

    document.content = raw
  end
end

Jekyll::Hooks.register :posts, :pre_render do |post, _payload|
  BloggerHtmlPreserver.capture(post)
end

Jekyll::Hooks.register :posts, :post_convert do |post|
  BloggerHtmlPreserver.restore(post)
end

Jekyll::Hooks.register :pages, :pre_render do |page, _payload|
  BloggerHtmlPreserver.capture(page)
end

Jekyll::Hooks.register :pages, :post_convert do |page|
  BloggerHtmlPreserver.restore(page)
end
