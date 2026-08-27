# Preserva o HTML original dos conteúdos importados do Blogger.
#
# O acervo migrado está em arquivos .md, mas o corpo já é HTML. Alguns posts
# antigos contêm combinações de tags que navegadores toleram, porém o Kramdown
# tenta normalizar e pode transformar tags em texto (&lt;div&gt;, &lt;iframe&gt; etc.).
#
# O projeto usa o stack `github-pages`, portanto adotamos hooks compatíveis com
# Jekyll 3.x: guardamos o HTML bruto em :pre_render e o recolocamos dentro do
# layout final em :post_render.
module BloggerHtmlPreserver
  RAW_CONTENT_KEY = "_blogger_raw_content".freeze
  POST_BODY_OPEN = '<div class="post-body">'.freeze
  POST_TAGS_OPEN = "\n  <div class=\"post-tags\"".freeze
  SHARE_OPEN = "\n  <section class=\"share-section\"".freeze
  MAIN_OPEN = '<main class="main-content" id="conteudo">'.freeze
  MAIN_CLOSE = '</main>'.freeze

  module_function

  def imported_from_blogger?(document)
    document.respond_to?(:data) && document.data["blogger_id"]
  end

  def capture(document)
    return unless imported_from_blogger?(document)

    document.data[RAW_CONTENT_KEY] = document.content.dup
  end

  def prepared_raw(document)
    raw = document.data.delete(RAW_CONTENT_KEY)
    return nil unless raw

    # Na prévia do GitHub Pages o site vive em /vamosaestudiarespanol.
    # No domínio oficial o baseurl é vazio, então nenhuma URL é alterada.
    baseurl = document.site.config["baseurl"].to_s.sub(%r{/$}, "")
    unless baseurl.empty?
      raw = raw.gsub(/\b(href|src)=(['"])\/(?!\/)([^'"]*)/i) do
        %(#{Regexp.last_match(1)}=#{Regexp.last_match(2)}#{baseurl}/#{Regexp.last_match(3)})
      end
    end

    raw
  end

  def restore_post(post)
    return unless imported_from_blogger?(post)

    raw = prepared_raw(post)
    return unless raw

    output = post.output.to_s
    body_open_at = output.index(POST_BODY_OPEN)
    unless body_open_at
      Jekyll.logger.warn "Blogger HTML:", "post-body não encontrado em #{post.path}"
      return
    end

    content_at = body_open_at + POST_BODY_OPEN.length
    tags_at = output.index(POST_TAGS_OPEN, content_at)
    share_at = output.index(SHARE_OPEN, content_at)
    boundary_at = [tags_at, share_at].compact.min
    unless boundary_at
      Jekyll.logger.warn "Blogger HTML:", "fim do post-body não encontrado em #{post.path}"
      return
    end

    # O trecho até a próxima seção inclui o conteúdo convertido e o </div> que
    # fecha .post-body. Recriamos somente esse miolo com o HTML original.
    output = output[0...content_at] + "\n" + raw + "\n  </div>" + output[boundary_at..-1]
    post.output = clean_related_excerpts(output)
  end

  def restore_page(page)
    return unless imported_from_blogger?(page)

    raw = prepared_raw(page)
    return unless raw

    output = page.output.to_s
    main_open_at = output.index(MAIN_OPEN)
    unless main_open_at
      Jekyll.logger.warn "Blogger HTML:", "main-content não encontrado em #{page.path}"
      return
    end

    content_at = main_open_at + MAIN_OPEN.length
    main_close_at = output.index(MAIN_CLOSE, content_at)
    unless main_close_at
      Jekyll.logger.warn "Blogger HTML:", "fim de main-content não encontrado em #{page.path}"
      return
    end

    page.output = output[0...content_at] + "\n" + raw + "\n    " + output[main_close_at..-1]
  end

  def clean_related_excerpts(output)
    start_at = output.index('<div class="related-grid">')
    return output unless start_at

    finish_at = output.index('</section>', start_at)
    return output unless finish_at

    segment = output[start_at...finish_at]
    escaped_tag = /&lt;\/?(?:div|span|br|ul|li|iframe|img|p|table|tbody|thead|tr|td|th|blockquote|h[1-6])\b.*?&gt;/im
    cleaned = segment.gsub(escaped_tag, "")
    output[0...start_at] + cleaned + output[finish_at..-1]
  end
end

Jekyll::Hooks.register :posts, :pre_render do |post, _payload|
  BloggerHtmlPreserver.capture(post)
end

Jekyll::Hooks.register :posts, :post_render do |post|
  BloggerHtmlPreserver.restore_post(post)
end

Jekyll::Hooks.register :pages, :pre_render do |page, _payload|
  BloggerHtmlPreserver.capture(page)
end

Jekyll::Hooks.register :pages, :post_render do |page|
  BloggerHtmlPreserver.restore_page(page)
end
