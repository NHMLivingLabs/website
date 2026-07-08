local BASELINE_YEAR = 1995
local current_year = tonumber(os.date("%Y"))
local years_of_research = math.max(0, current_year - BASELINE_YEAR)

function Span(el)
  if el.classes:includes("current-year") then
    return pandoc.Str(tostring(current_year))
  end

  if el.classes:includes("years-of-research") then
    return pandoc.Str(tostring(years_of_research))
  end

  return el
end
