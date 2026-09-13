-- the link is left empty (CSS draws the "#") so the TOC entries don't pick up the marker
function Header(h)
  if h.identifier ~= "" then
    h.content:insert(pandoc.Link({}, "#" .. h.identifier, "", {class = "anchor"}))
  end
  return h
end
