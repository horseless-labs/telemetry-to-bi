influx query '
import "influxdata/influxdb/schema"

tags =
  schema.tagKeys(bucket: "wimbac")
    |> map(fn: (r) => ({
      kind: "tag",
      name: r._value
    }))

fields =
  schema.fieldKeys(bucket: "wimbac")
    |> map(fn: (r) => ({
      kind: "field",
      name: r._value
    }))

union(tables: [tags, fields])
  |> sort(columns: ["kind", "name"])
'