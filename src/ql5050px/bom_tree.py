"""Nested assembly BOM explosion with explicit purchase boundaries."""
from .drawing_bom import build_bom


def explode_bom(catalog, root, *, include_subassemblies=False, expand_purchased=False):
    """Catalog maps stable ids to part_number/material/children/quantity rows.

    Children are {ref, quantity}; quantity multiplies through the hierarchy.
    Purchased assemblies remain a single procurement row unless opted in.
    Reused assemblies are legal; cycles in the current ancestry are rejected.
    """
    flattened, structure = [],[]
    def visit(ref, count, trail):
        if ref in trail:
            raise ValueError("BOM cycle: " + " -> ".join(trail+[ref]))
        if ref not in catalog:
            raise ValueError(f"missing BOM catalog reference: {ref}")
        row = catalog[ref]
        children = row.get("children",[])
        leaf = not children or (row.get("purchased") and not expand_purchased)
        path = trail+[ref]
        structure.append({"path":path,"quantity":count,"leaf":leaf,"part_number":row["part_number"]})
        if leaf or include_subassemblies:
            flattened.append({**row,"id":"/".join(path),"quantity":count})
        if not leaf:
            for child in children:
                qty = child.get("quantity",1)
                if isinstance(qty,bool) or not isinstance(qty,int) or qty<=0:
                    raise ValueError("child quantity must be positive integer")
                visit(child["ref"],count*qty,path)
    visit(root,1,[])
    return {"bom":build_bom(flattened),"structure":structure,"root":root,
            "scope":"with_subassemblies" if include_subassemblies else "procurement_leaves",
            "native_status":"unverified"}


def compare_boms(before, after):
    def keyed(rows):
        result = {}
        for row in rows:
            key = (row["part_number"],row.get("configuration",""),row.get("material"),bool(row.get("purchased")))
            result[key] = result.get(key,0)+row["quantity"]
        return result
    old,new = keyed(before),keyed(after)
    return [{"part_number":key[0],"configuration":key[1],"material":key[2],"purchased":key[3],
             "before_quantity":old.get(key,0),"after_quantity":new.get(key,0),
             "delta":new.get(key,0)-old.get(key,0)}
            for key in sorted(old.keys()|new.keys(),key=str) if old.get(key,0)!=new.get(key,0)]
